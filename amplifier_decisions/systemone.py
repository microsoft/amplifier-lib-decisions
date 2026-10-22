"""Pure System One wire codec shared by TypeSafe and Microsoft providers.

No transport, credential lookup, endpoint discovery or Amplifier imports.
"""
import base64
import io
import json
import math
import re
import uuid
from .contracts import Answer, Capabilities


def _number(value, low=0, high=1):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("invalid_number")
    return float(value)


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class SystemOneCodec:
    def __init__(self, model, *, experimental_images=False):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("An explicit decision model is required")
        self.model = model.strip()
        self.experimental_images = experimental_images
        self.capabilities = Capabilities(images=experimental_images)

    def _body(self, request):
        if request.allow_external_state is not True:
            raise ValueError("external_state_disabled")
        if not isinstance(request.state, (str, dict, list)):
            raise ValueError("invalid_state")
        _number(request.timeout_seconds, .01, 120)
        caps = self.capabilities
        if not 1 <= len(request.questions) <= caps.max_questions:
            raise ValueError("question_limit")
        if len({q.name for q in request.questions}) != len(request.questions):
            raise ValueError("duplicate_questions")
        for q in request.questions:
            if not isinstance(q.name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", q.name):
                raise ValueError("invalid_question_name")
            if q.kind not in caps.kinds:
                raise ValueError("unsupported_question")
            if not isinstance(q.instructions, str) or not q.instructions.strip():
                raise ValueError("invalid_instructions")
            if q.kind == "choice":
                if not 2 <= len(q.choices) <= caps.max_choices or any(
                    not isinstance(k, str) or not k or not isinstance(v, str) for k, v in q.choices.items()):
                    raise ValueError("invalid_choices")
            elif q.choices:
                raise ValueError("unexpected_choices")
            if q.kind == "score":
                if not 2 <= len(q.levels) <= caps.max_levels or any(not isinstance(x, str) or not x for x in q.levels):
                    raise ValueError("invalid_levels")
            elif q.levels:
                raise ValueError("unexpected_levels")
        text = _json({"state": request.state, "questions": [vars(q) for q in request.questions]})
        if len(text.encode()) > caps.max_text_bytes:
            raise ValueError("local_text_limit")
        if len(request.images) > caps.max_images or (request.images and not caps.images):
            raise ValueError("unsupported_images")
        if any(q.kind == "box" for q in request.questions) and len(request.images) != 1:
            raise ValueError("box_requires_one_image")
        encoded = []
        for img in request.images:
            if img.media_type not in {"image/png", "image/jpeg"} or not 0 < len(img.data) <= 16 * 1024**2:
                raise ValueError("invalid_image")
            try:
                from PIL import Image as PILImage
                with PILImage.open(io.BytesIO(img.data)) as opened:
                    width, height = opened.size
                    if opened.format != {"image/png": "PNG", "image/jpeg": "JPEG"}[img.media_type]:
                        raise ValueError("image_format_mismatch")
                    if self.experimental_images and (not 280 <= width <= 1568 or not 280 <= height <= 1568
                        or not 78_400 <= width * height <= 2_458_624):
                        raise ValueError("image_dimensions")
                    opened.verify()
            except ImportError:
                raise ValueError("install_images_extra") from None
            except (OSError, SyntaxError):
                raise ValueError("invalid_image") from None
            encoded.append(base64.b64encode(img.data).decode("ascii"))
        questions = {}
        for q in request.questions:
            row = {"type": "noul" if q.kind == "predicate" else q.kind, "instructions": q.instructions}
            if q.kind == "choice": row["criteria"] = q.choices
            if q.kind == "score": row["criteria"] = list(q.levels)
            questions[q.name] = row
        body = {"model": self.model, "state": request.state, "questions": questions}
        if encoded:
            refs = [str(uuid.uuid4()) for _ in encoded]
            body["state"] = {"observation": request.state, "images": refs}
            body["assets"] = {ref: {"type": "image", "format": "png" if img.media_type == "image/png" else "jpg",
                "data_base64": data} for ref, img, data in zip(refs, request.images, encoded)}
        content = _json(body).encode()
        if len(content) > 32 * 1024**2:
            raise ValueError("body_limit")
        return content

    def _answer(self, q, row):
        try:
            if not isinstance(row, dict):
                raise ValueError("missing_answer")
            if row.get("type") == "refusal":
                return Answer(q.name, q.kind, "refused", reason="provider_refusal")
            expected = "noul" if q.kind == "predicate" else q.kind
            if row.get("type") != expected:
                raise ValueError("answer_type")
            if q.kind == "predicate":
                return Answer(q.name, q.kind, "answered", _number(row.get("noul")))
            confidence = _number(row.get("confidence"))
            if q.kind == "box":
                box = row["box"]
                if not isinstance(box, dict) or set(box) != {"left", "right", "top", "bottom"}:
                    raise ValueError("invalid_box")
                box = {k: _number(v) for k, v in box.items()}
                if box["left"] >= box["right"] or box["top"] >= box["bottom"]:
                    raise ValueError("invalid_box")
                return Answer(q.name, q.kind, "answered", box, confidence=confidence)
            raw = row["probabilities"]
            if not isinstance(raw, dict): raise ValueError("probability_shape")
            probabilities = {k: _number(v) for k, v in raw.items()}
            keys = set(q.choices) if q.kind == "choice" else {str(i) for i in range(len(q.levels))}
            if set(probabilities) != keys or abs(sum(probabilities.values()) - 1) > .001:
                raise ValueError("probability_distribution")
            if q.kind == "choice":
                value = row["choice"]
                if not isinstance(value, str) or value not in keys or probabilities[value] < max(probabilities.values()) - .000001:
                    raise ValueError("invalid_choice")
            else:
                value = _number(row["score"], 0, len(q.levels) - 1)
                if abs(value - sum(int(k)*p for k, p in probabilities.items())) > .001:
                    raise ValueError("inconsistent_score")
            return Answer(q.name, q.kind, "answered", value, probabilities, confidence)
        except (KeyError, TypeError, ValueError):
            return Answer(q.name, q.kind, "invalid", reason="invalid_answer")
