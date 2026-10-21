"""Explicit generic metrics. Confirm aggregation against paper before reporting."""
import math


def macro_f1(truth, predicted, labels):
    if len(truth) != len(predicted) or not labels or not truth:
        raise ValueError('需要配对的真实/预测答案，以及显式选项编码')
    if any(x not in labels for x in truth + predicted):
        raise ValueError('存在未编码或无效答案；请先处理缺失值')
    scores = []
    for label in labels:
        tp = sum(t == label and p == label for t, p in zip(truth, predicted))
        fp = sum(t != label and p == label for t, p in zip(truth, predicted))
        fn = sum(t == label and p != label for t, p in zip(truth, predicted))
        scores.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0)
    return sum(scores) / len(scores)


def one_minus_js(p, q):
    """1 minus Jensen–Shannon divergence, log base 2 (not sqrt distance)."""
    if len(p) != len(q) or not p or any(not math.isfinite(x) or x < 0 for x in p + q):
        raise ValueError('需要长度相同的非负有限分布')
    if sum(p) <= 0 or sum(q) <= 0:
        raise ValueError('分布总和必须大于零')
    p, q = [x / sum(p) for x in p], [x / sum(q) for x in q]
    m = [(a + b) / 2 for a, b in zip(p, q)]
    kl = lambda a: sum(x * math.log2(x / y) for x, y in zip(a, m) if x)
    return 1 - (kl(p) + kl(q)) / 2
