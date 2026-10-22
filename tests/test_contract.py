import asyncio
import json
import pytest
from amplifier_decisions import DecisionRequest, Question
from amplifier_decisions.systemone import SystemOneCodec
from amplifier_decisions.runtime import SystemOneBackend

Q=Question('next','choice','Choose',{'a':'Save','b':'Cancel'})
@pytest.mark.parametrize('patch',[{'choice':'unknown'},{'choice':'b'},{'probabilities':{'a':.9}},{'probabilities':{'a':.9,'b':.9}},{'confidence':True},{'confidence':1.5},{'probabilities':{'a':'0.9','b':.1}},{'type':'predicate'}])
def test_malformed_choice_cannot_authorize_action(patch):
    row={'type':'choice','choice':'a','probabilities':{'a':.9,'b':.1},'confidence':.8,**patch}
    assert SystemOneCodec('test')._answer(Q,row).status=='invalid'

@pytest.mark.parametrize('decision_request',[DecisionRequest('x',(Q,)),DecisionRequest('x',(Q,Q),allow_external_state=True),DecisionRequest('x',(),allow_external_state=True),DecisionRequest({'x':float('nan')},(Q,),allow_external_state=True),DecisionRequest('x',(Q,),timeout_seconds=True,allow_external_state=True)])
async def test_invalid_input_has_no_transport_effect(decision_request):
    sent=[]
    async def send(*args):sent.append(args)
    result=await SystemOneBackend('fixture','model',send).decide(decision_request)
    assert sent==[] and all(a.status=='invalid' for a in result.answers.values())

async def test_partial_and_closed_outcomes_are_distinct():
    async def send(*args):return {'answers':{'next':{'type':'refusal'}}},None
    backend=SystemOneBackend('fixture','model',send)
    result=await backend.decide(DecisionRequest('x',(Q,Question('other','predicate','Visible?')),allow_external_state=True))
    assert result.answers['next'].status=='refused' and result.answers['other'].status=='invalid'
    await backend.close()
    assert (await backend.decide(DecisionRequest('x',(Q,),allow_external_state=True))).answers['next'].reason=='closed'
