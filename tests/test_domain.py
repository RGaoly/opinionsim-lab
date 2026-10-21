import json
import pytest
from opinionsim.domain import anonymize,read_csv,validate_template,render,parse_answer,validate_config,price
from opinionsim.example import default_config
from opinionsim.security import hash_password,verify_password,validate_endpoint
from opinionsim.analysis import macro_f1,one_minus_js


def test_deidentification_and_truth_separation():
    clean = anonymize([{'name':'Private Name','email':'a@example.org','age':'24','q1':'C'}],
                       {'age':'age'},{'q1':'q1'},b'unit-test-salt')
    assert clean[0]['profile']=={'age_band':'20–29'}
    assert 'Private Name' not in json.dumps(clean)
    prompt = render(default_config(),{'question_idx':0,'prompt_idx':0,'language':'zh'},clean[0]['profile'])
    assert 'truth' not in prompt
    assert clean[0]['truth']=={'q1':'C'}


def test_pii_and_answer_leakage_rejected():
    with pytest.raises(ValueError):
        anonymize([{'gender':'a@example.org'}],{'gender':'gender'},{},b'salt')
    with pytest.raises(ValueError):
        anonymize([{'q1':'A'}],{'gender':'q1'},{'q1':'q1'},b'salt')


def test_template_cannot_traverse_fields():
    with pytest.raises(ValueError):
        validate_template('{profile.__class__} {question} {choices}')
    with pytest.raises(ValueError):
        validate_template('{truth} {profile} {question} {choices}')


def test_language_templates_and_factor_count():
    c = default_config()
    validate_config(c)
    a = render(c,{'question_idx':0,'prompt_idx':0,'language':'en'},{'age_band':'20–29'})
    b = render(c,{'question_idx':0,'prompt_idx':0,'language':'zh'},{'age_band':'20–29'})
    assert 'Question:' in a and '问题：' in b
    assert 2000*len(c['models'])*len(c['languages'])*len(c['prompts'])*len(c['questions'])==192000


def test_nonfinite_prices_and_language_codes_rejected():
    c = default_config()
    c['models'][0]['input_price']=float('nan')
    with pytest.raises(ValueError):
        validate_config(c)
    c = default_config()
    c['questions'][0]['choices']['en']['D']='Other'
    with pytest.raises(ValueError):
        validate_config(c)


def test_parse_is_strict_and_preserves_failures():
    assert parse_answer('{"answer":"A"}',{'A':'yes'})==('A',None)
    assert parse_answer('Here is my answer: A',{'A':'yes'})[0] is None
    assert parse_answer('{"answer":"D"}',{'A':'yes'})[0] is None


def test_metrics_semantics():
    assert macro_f1(['A','B'],['A','B'],['A','B'])==1
    assert one_minus_js([1,0],[0,1])==0
    assert one_minus_js([1,1],[2,2])==1
    with pytest.raises(ValueError):
        one_minus_js([0,0],[1,1])


def test_password_hash_and_endpoint_allowlist():
    p = hash_password('long-test-password')
    assert verify_password('long-test-password',p)
    assert not verify_password('wrong-password',p)
    for url in ['http://api.openai.com/v1','https://127.0.0.1/v1','https://api.openai.com.evil.test/v1',
                'https://user:pass@api.openai.com/v1','https://api.openai.com:8443/v1']:
        with pytest.raises(ValueError):
            validate_endpoint(url)


def test_csv_shape_and_formula_escape():
    from opinionsim.export import safe_cell
    with pytest.raises(ValueError):
        read_csv(b'a,b\n1,2,3\n')
    assert safe_cell('=SUM(A1:A2)').startswith("'")
