from app import reasoning as r

def test_draft_and_critique_receive_same_relationship_context(monkeypatch):
    seen=[]
    def complete(settings,system,data,schema,tokens):
        seen.append(data)
        return {'claims':[]} if 'claims' in schema['properties'] else {'accepted_ids':[]}
    monkeypatch.setattr(r,'complete',complete)
    lead={'kind':'shared_identifier','description':'Different names share a captured phone.','capture_ids':['p'],'requires_review':True}
    cap={'id':'c','business_id':'b','final_url':'https://example.com','text':'Our team performs the work directly for customers.','sha256':'abc','observed_at':'today'}
    result=r.assess({'id':'b','name':'Example','website':'https://example.com'},[cap],{'model':'test'},relationships=[lead])
    assert result['status']=='assessed'
    assert len(seen)==2 and all(x['relationship_leads']==[lead] for x in seen)
