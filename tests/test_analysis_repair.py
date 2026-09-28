import pytest
from app import reasoning as r
from app.conclusion import work_account,combine

@pytest.mark.parametrize('text',[
 'The team did a fantastic job installing our new HVAC ducts and vents.',
 'From the initial estimate to the final installation, the process was seamless. They cleaned up afterwards.',
 'My house had never had duct cleaning. The crew arrived and completed the replacement.',
 'Crew of 3 arrived on time and protected the floors.',
 'This team sealed my attic to stop rats.',
 'The team did an excellent job cleaning my rental attic.',
 'Came and inspected my crawlspace and rodent-proofed it.',
 'They did excellent rodent-proofing work in our attic.',
])
def test_concrete_work_accounts(text):assert work_account(text)

@pytest.mark.parametrize('text',['They never completed the work.','They did not install the insulation.','I need installation and got a quote.','Wonderful people, highly recommended!','Sam gave helpful advice about insulation.'])
def test_no_completed_work_claim(text):assert not work_account(text)

def test_external_role_mistake_is_attributed_not_promoted(monkeypatch):
    quote='They installed insulation in our attic and cleaned up.'
    source={'capture_id':'review','source_type':'customer_review','text':quote}
    raw={'claims':[{'id':'one','dimension':'business_role','interpretation':'direct_provider','statement':'The operator says it performs insulation work.','evidence_id':'E1','limitation':'Website self-description; operation not independently verified.'}]}
    draft=r.resolve_evidence(raw,r.evidence_index([source]),[source])
    c=draft.claims[0]
    assert c.dimension=='corroboration' and c.interpretation=='other_claim'
    assert c.statement=='Customer account: '+quote and c.quote==quote
    assert 'operator says' not in c.statement

def test_failure_is_not_a_business_uncertainty():
    assert combine({'status':'failed','error':'bad model output'},{},{})['label']=='Analysis failed — retry needed'
    assert combine({'status':'assessed','claims':[]},{},{})['label']=='Not enough evidence to assess lead-gen risk'

def test_duplicate_review_not_multiple_independent_accounts():
    e={'kind':'customer_review','capture_id':'r','quote':'They installed the insulation.'}
    r=combine({'status':'assessed','claims':[]},{'evidence':[e,e]},{})
    assert not r['label'].startswith('Unlikely')
