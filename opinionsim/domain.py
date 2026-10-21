"""Pure validation, anonymisation, prompt rendering, and pricing logic."""
import csv
import hashlib
import hmac
import io
import json
import math
import re
import string
from decimal import Decimal, ROUND_CEILING

MONEY = Decimal('0.00000001')
PROFILE_FIELDS = {'age', 'age_band', 'gender', 'education', 'income_band',
                  'region', 'occupation_group', 'urban_rural'}
PII = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)\d{17}[\dXx](?!\d)')
PROMPTS = [
    ('direct', 'You are simulating one survey respondent. Profile: {profile}\nLanguage: {language}\nQuestion: {question}\nOptions: {choices}\nReturn only JSON with one field "answer" containing the option code.'),
    ('cot', 'Simulate this respondent: {profile}\nUse {language}. Question: {question}\nOptions: {choices}\nConsider the response step by step, then return JSON with "answer" (option code) and "rationale".'),
    ('persona', 'Answer as the person described here: {profile}\nUse {language}. Question: {question}\nOptions: {choices}\nChoose their likely opinion. Return only JSON with "answer" (option code).'),
    ('persona_cot', 'Take the perspective of this person: {profile}\nUse {language}. Question: {question}\nOptions: {choices}\nExplain briefly how their circumstances may shape their opinion. Return JSON with "answer" (option code) and "rationale".')
]
PROMPTS_ZH = {
    'direct':'模拟一位调查受访者。画像：{profile}\n语言：{language}\n问题：{question}\n选项：{choices}\n只返回 JSON，字段 answer 为选项编码。',
    'cot':'模拟这位受访者：{profile}\n语言：{language}\n问题：{question}\n选项：{choices}\n逐步考虑回答，返回 JSON，字段 answer 为选项编码，rationale 为理由。',
    'persona':'请以此人的身份回答：{profile}\n语言：{language}\n问题：{question}\n选项：{choices}\n选择其可能持有的意见。只返回 JSON，字段 answer 为选项编码。',
    'persona_cot':'从此人的角度作答：{profile}\n语言：{language}\n问题：{question}\n选项：{choices}\n简述其处境如何影响意见。返回 JSON，字段 answer 为选项编码，rationale 为理由。'
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read_csv(data):
    if len(data) > 20 * 1024 * 1024:
        raise ValueError('CSV 上限 20 MB；请先本地删去不需要的字段')
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError('CSV 必须有唯一列名')
    records = []
    for row in reader:
        if None in row or len(records) >= 10000:
            raise ValueError('CSV 存在不齐整的行，或超过 10,000 名受访者')
        records.append(row)
    if not records:
        raise ValueError('CSV 没有数据')
    return reader.fieldnames, records


def anonymize(records, mapping, truth_columns, salt):
    if not mapping or not set(mapping).issubset(PROFILE_FIELDS):
        raise ValueError('只能选择白名单人口统计字段')
    if set(mapping.values()) & set(truth_columns.values()):
        raise ValueError('真实回答不能同时作为人物画像')
    result = []
    for i, row in enumerate(records):
        profile = {}
        for target, source in mapping.items():
            v = str(row.get(source, '') or '').strip()
            if len(v) > 80 or PII.search(v):
                raise ValueError(f'第 {i + 1} 行所选画像含疑似个人标识或长文本，请先检查')
            if target == 'age' and v:
                age = int(v)
                if not 0 <= age <= 120:
                    raise ValueError('年龄超出有效范围')
                target, v = 'age_band', f'{age // 10 * 10}–{age // 10 * 10 + 9}'
            profile[target] = v
        truth = {qid: str(row.get(col, '') or '').strip() for qid, col in truth_columns.items()}
        if any(PII.search(v) or len(v) > 20 for v in truth.values()):
            raise ValueError('真实回答列必须使用短选项编码，不能包含个人信息')
        rid = hmac.new(salt, str(i).encode(), hashlib.sha256).hexdigest()[:24]
        result.append({'rid': rid, 'profile': profile, 'truth': truth})
    return result


def validate_template(body):
    fields = []
    try:
        for _, field, spec, conv in string.Formatter().parse(body):
            if field is not None:
                if field not in {'profile', 'question', 'choices', 'language'} or spec or conv:
                    raise ValueError('仅允许 {profile} {question} {choices} {language} 四种变量；JSON 花括号请双写')
                fields.append(field)
    except ValueError:
        raise ValueError('提示语格式错误：只用四种规定变量；其他花括号须写成 {{ 和 }}')
    if not {'profile', 'question', 'choices'}.issubset(fields) or len(body) > 20000:
        raise ValueError('提示语需要画像、问题和选项，且不得超过 20,000 字符')


def render(config, task, profile):
    q = config['questions'][task['question_idx']]
    language = task['language']
    p = config['prompts'][task['prompt_idx']]
    template = (p.get('body_en') or p['body']) if language == 'en' else p['body']
    return template.format(
        profile=canonical(profile), language=language,
        question=q['text'][language], choices=canonical(q['choices'][language]))


def price(model, input_tokens, output_tokens):
    amount = (Decimal(str(model['input_price'])) * input_tokens
              + Decimal(str(model['output_price'])) * output_tokens) / Decimal(1_000_000)
    return amount.quantize(MONEY, rounding=ROUND_CEILING)


def reserve_cost(model, prompt, max_output):
    # Conservative for byte-based tokenizers, with protocol overhead allowance.
    # Verify tokenizer/pricing for each provider before a paid run.
    return price(model, len(prompt.encode('utf-8')) + 256, max_output)


def validate_config(config):
    if len(config['models']) != 2 or len(config['prompts']) != 4 or len(config['questions']) != 6:
        raise ValueError('本实验设计固定为 2 模型 × 2 语言 × 4 提示 × 6 题')
    if config['languages'] != ['zh', 'en']:
        raise ValueError('语言须为 zh 和 en')
    if len({q['id'] for q in config['questions']}) != 6:
        raise ValueError('题目 ID 必须唯一')
    if not 1 <= config['repetitions'] <= 100 or not 16 <= config['max_output_tokens'] <= 8192:
        raise ValueError('重复次数或输出上限超出范围')
    if config['currency'] not in ('CNY', 'USD'):
        raise ValueError('统一使用 CNY 或 USD 计价，不能混合币种')
    for p in config['prompts']:
        validate_template(p['body'])
        if p.get('body_en'):
            validate_template(p['body_en'])
    for q in config['questions']:
        for lang in config['languages']:
            if not q['text'].get(lang) or not isinstance(q['choices'].get(lang), dict) or len(q['choices'][lang]) < 2:
                raise ValueError('每题必须含中英文题干和至少两个选项')
        if set(q['choices']['zh']) != set(q['choices']['en']):
            raise ValueError('中英文必须使用相同选项编码')
    if len({m['label'] for m in config['models']}) != 2:
        raise ValueError('两个模型标签需要不同')
    for m in config['models']:
        if m['provider'] not in ('mock', 'compatible') or not m['model']:
            raise ValueError('模型配置错误')
        for key in ('input_price', 'output_price'):
            n = Decimal(str(m[key]))
            if not n.is_finite() or n < 0 or (m['provider'] != 'mock' and n == 0):
                raise ValueError('真实模型需填写正数单价；不扣除免费额度，按原价预留预算')
        if m['provider'] == 'compatible' and not m.get('credential_id'):
            raise ValueError('真实模型需要有效凭据')
        if set(m.get('parameters', {})) - {'temperature', 'top_p', 'seed', 'enable_thinking'}:
            raise ValueError('仅支持 temperature/top_p/seed/enable_thinking 参数')
    canonical(config)


def parse_answer(raw, choices):
    try:
        value = json.loads(raw.strip())
        answer = str(value['answer'])
        if answer not in choices:
            raise ValueError()
        return answer, None
    except (ValueError, KeyError, TypeError):
        return None, 'invalid_answer_json_or_option'
