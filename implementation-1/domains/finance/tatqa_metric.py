"""TAT-QA / TAT-HQA answer metric, vendored so the finance scorer runs without the raw data folder.

Copied verbatim from the TAT-HQA repository (github.com/NExTplusplus/TAT-HQA, Apache-2.0, Copyright the
TAT-HQA authors): every function of `tatqa_utils.py`, and from `tag_op/tatqa_metric.py` (the module the
official `tatqa_eval.py` imports) the functions `_answer_to_bags`, `_align_bags`, `_compute_f1`, `get_metrics`,
`extract_gold_answers`, `metric_max_over_ground_truths`, `get_answer_str`, `add_percent_pred`.

Modifications (and nothing else):
- Three regex literals in `negative_num_handle`, `percent_num_handle` and `word_scale_handle` are written as raw
  strings (same string value; avoids Python's invalid-escape warning).
- `linear_sum_assignment` (scipy.optimize, used by `_align_bags`) is replaced by the pure-Python
  `linear_sum_assignment` below (Hungarian algorithm, same optimum), because scipy is not installed here.
- The scoring core of `TaTQAEmAndF1.__call__` is `em_f1` below (same statements, without the running totals,
  the unused span metrics and a debug print). The accumulator and its pandas pivot tables are not copied.
`domains/finance/validate.py` checks that every copied function is AST-identical to the original and that
`em_f1` agrees with the original class on every gold answer and on perturbed predictions.
"""
import re
import string
from typing import Any, Dict, List, Set, Tuple, Union

import numpy as np

def scale_to_num(scale):
    scale = scale.lower()
    num = 1
    if 'hundred' in scale:  # hundred
        num = 100
    elif 'thousand' in scale:  # thousand
        num = 1000
    elif 'million' in scale:  # million
        num = 1000000
    elif 'billion' in scale:  # billion
        num = 1000000000
    elif 'percent' in scale:  # percent
        num = 0.01
    return num


def extract_one_num_from_str(s):
    s = _clean_num(s)
    r_num = r"([+-]?\d+(\.\d+)?)|([+-]?\.\d+)"
    groups = re.findall(r_num, s)
    if len(groups) == 0:
        return None
    num = groups[0][0]
    if num == '':
        return None
    if '.' in num:
        return float(num)
    return int(num)


EXCLUDE_IN_NUM = "'\"\\$€£¥%(),[]"


def _clean_num(text:str):
    return "".join([ch for ch in str(text) if ch not in EXCLUDE_IN_NUM])


def is_number(text: str) -> bool:
    try:
        words = " ".join([_clean_num(w) for w in text.split()]).split()
        if len(words) == 0:
            """1023 or 1 million"""
            return False
        num = float(words[0])
        if np.isnan(num):
            return False
        if len(words) >= 2:
            if scale_to_num(words[1]) == 1:
                return False
        return True
    except ValueError:
        return False


def negative_num_handle(x):
    """
    :param x:  transform (134) -> -134
    :return:
    """
    all = re.findall(r'(\([\d.\s]+\))', x.strip())
    if len(all) > 0:
        return -1
    return 1


def percent_num_handle(x):
    """
    :param x:  transform 12% -> 12/100
    :return:
    """
    all = re.findall(r'([\d.\s]+%)', x.strip())
    if len(all) > 0:
        return 0.01
    return 1


def word_scale_handle(x):
    """
    :param x: 1 million = 1,000,000
    :return:
    """
    iter = re.finditer(r'([\d.]+\s?[a-zA-Z]+)', x)
    for one in iter:
        text = one.group(0).lower()
        scale_val = scale_to_num(text)
        return scale_val
    return 1


def to_number(text:str) -> float:
    num = extract_one_num_from_str(text)
    scale_val = word_scale_handle(text)
    negative_flag = negative_num_handle(text)
    percent_flag = percent_num_handle(text)
    if num is not None:
        return round(num * scale_val * negative_flag * percent_flag, 4)
    return None


def remove_articles(text: str) -> str:
    regex = re.compile(r'\b(a|an|the)\b', re.UNICODE)
    return re.sub(regex, ' ', text)


def white_space_fix(text: str) -> str:
    return ' '.join(text.split())


EXCLUDE = set(string.punctuation)


def remove_punc(text: str) -> str:
    if not is_number(text):
        return ''.join(ch for ch in text if ch not in EXCLUDE)
    else:
        return text


def lower(text: str) -> str:
    return text.lower()


def tokenize(text: str) -> List[str]:
    return re.split(" ", text)


def normalize_number(text: str) -> str:
    if is_number(text):
        return str(to_number(text))
    else:
        return text


def normalize_answer(text: str) -> str:
    """Lower text and remove punctuation, articles and extra whitespace."""
    parts = [white_space_fix(remove_articles(normalize_number(remove_punc(lower(token)))))
             for token in tokenize(text)]
    parts = [part for part in parts if part.strip()]
    normalized = ' '.join(parts).strip()
    return normalized


STRIPPED_CHARACTERS = string.punctuation + ''.join([u"‘", u"’", u"´", u"`", "_"])


def ws_tokenize(text):
    """Runs basic whitespace cleaning and splitting on a piece of text."""
    text = text.strip().lower()
    if not text:
        return []
    text = white_space_fix(text)
    tokens = text.split()
    tokens = [token.strip(STRIPPED_CHARACTERS) for token in tokens]
    return tokens


def linear_sum_assignment(cost):
    """Minimum-cost assignment of a rectangular matrix, like scipy.optimize.linear_sum_assignment: returns
    (row_ind, col_ind) for min(n_rows, n_cols) pairs, rows in increasing order (Hungarian algorithm, O(n^3))."""
    cost = np.asarray(cost, dtype=float)
    n_r, n_c = cost.shape
    if n_r == 0 or n_c == 0:
        return np.array([], dtype=int), np.array([], dtype=int)
    n = max(n_r, n_c)
    a = np.zeros((n + 1, n + 1))
    a[1:n_r + 1, 1:n_c + 1] = cost   # padding rows/cols cost 0, so they never change the optimum
    u, v = [0.0] * (n + 1), [0.0] * (n + 1)
    p, way = [0] * (n + 1), [0] * (n + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [float("inf")] * (n + 1), [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], float("inf"), 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = a[i0][j] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    pairs = sorted((p[j] - 1, j - 1) for j in range(1, n + 1) if 0 < p[j] <= n_r and j <= n_c)
    return np.array([r for r, _ in pairs], dtype=int), np.array([c for _, c in pairs], dtype=int)


def _answer_to_bags(answer: Union[str, List[str], Tuple[str, ...]]) -> Tuple[List[str], List[Set[str]]]:
    if isinstance(answer, (list, tuple)):
        raw_spans = answer
    else:
        raw_spans = [answer]
    normalized_spans: List[str] = []
    token_bags = []
    for raw_span in raw_spans:
        normalized_span = normalize_answer(raw_span)
        normalized_spans.append(normalized_span)
        token_bags.append(set(normalized_span.split()))
    return normalized_spans, token_bags


def _align_bags(predicted: List[Set[str]], gold: List[Set[str]]) -> List[float]:
    """
    Takes gold and predicted answer sets and first finds the optimal 1-1 alignment
    between them and gets maximum metric values over all the answers.
    """
    scores = np.zeros([len(gold), len(predicted)])
    for gold_index, gold_item in enumerate(gold):
        for pred_index, pred_item in enumerate(predicted):
            # if _match_numbers_if_present(gold_item, pred_item): no need to match number in tatqa
            scores[gold_index, pred_index] = _compute_f1(pred_item, gold_item)
    row_ind, col_ind = linear_sum_assignment(-scores)

    max_scores = np.zeros([max(len(gold), len(predicted))])
    for row, column in zip(row_ind, col_ind):
        max_scores[row] = max(max_scores[row], scores[row, column])
    return max_scores


def _compute_f1(predicted_bag: Set[str], gold_bag: Set[str]) -> float:
    intersection = len(gold_bag.intersection(predicted_bag))
    if not predicted_bag:
        precision = 1.0
    else:
        precision = intersection / float(len(predicted_bag))
    if not gold_bag:
        recall = 1.0
    else:
        recall = intersection / float(len(gold_bag))
    f1 = (2 * precision * recall) / (precision + recall) if not (precision == 0.0 and recall == 0.0) else 0.0
    return f1


def get_metrics(predicted: Union[str, List[str], Tuple[str, ...]],
                gold: Union[str, List[str], Tuple[str, ...]]) -> Tuple[float, float]:
    """
    Takes a predicted answer and a gold answer (that are both either a string or a list of
    strings), and returns exact match and the DROP F1 metric for the prediction.  If you are
    writing a script for evaluating objects in memory (say, the output of predictions during
    validation, or while training), this is the function you want to call, after using
    :func:`answer_json_to_strings` when reading the gold answer from the released data file.
    """
    predicted_bags = _answer_to_bags(predicted)
    gold_bags = _answer_to_bags(gold)
    # print("pred bags:" + str(predicted_bags))
    # print("answer bags:" + str(predicted_bags))

    if set(predicted_bags[0]) == set(gold_bags[0]) and len(predicted_bags[0]) == len(gold_bags[0]):
        exact_match = 1.0
    else:
        exact_match = 0.0

    f1_per_bag = _align_bags(predicted_bags[1], gold_bags[1])
    f1 = np.mean(f1_per_bag)
    f1 = round(f1, 2)
    return exact_match, f1


def extract_gold_answers(qa_annotation):
    '''
    span
    multi-span
    arithmetic (+ - * /)
    count
    date
    other
    gold answers is a list of list, each item in gold answers is a valid answer
    '''
    answer_type, scale = qa_annotation["answer_type"], qa_annotation['scale']
    answer_content = qa_annotation['answer']
    gold_answers = []
    if answer_type in ['multi-span', 'span']: # list
        assert isinstance(answer_content, list), answer_content
        gold_answers = answer_content # multi-span
    elif answer_type in ["arithmetic"]:
        gold_answers.append(str(answer_content))
    elif answer_type in ['count']:
        gold_answers.append(str(int(answer_content)))
    else:
        gold_answers.append(str(answer_content))
    # elif answer_type == 'date': # to add date process
    #     gold_answers.append("{0} {1} {2}".format(answer_content[0], answer_content[1], answer_content[2]))
    return answer_type, gold_answers, scale


def metric_max_over_ground_truths(metric_fn, predictions, ground_truths):
    scores_for_ground_truths = []
    for pred in predictions:
        for ground_truth in ground_truths:
            score = metric_fn(pred, ground_truth)
            scores_for_ground_truths.append(score)
    if len(scores_for_ground_truths) == 0:
        return 0, 0
    return max(scores_for_ground_truths)


def get_answer_str(answers: list, scale: str):
    """
    :param ans_type:  span, multi-span, arithmetic, count
    :param ans_list:
    :param scale: "", thousand, million, billion, percent
    :param mode:
    :return:

    """
    sorted_ans = sorted(answers)
    ans_temp = []
    for ans in sorted_ans:
        ans_str = str(ans)
        if is_number(ans_str):
            ans_num = to_number(ans_str)
            if ans_num is None:
                if scale:
                    ans_str = ans_str + " " + str(scale)
            else:
                if '%' in ans_str: #  has been handled the answer itself is a percentage
                    ans_str = '%.4f' % ans_num
                else:
                    ans_str = '%.4f' % (round(ans_num, 2) * scale_to_num(scale))
        else:
            if scale:
                ans_str = ans_str + " " + str(scale)
        ans_temp.append(ans_str)
    return [" ".join(ans_temp)]


def add_percent_pred(prediction_strings, pred_scale, pred):
    """
    to solve [pred = 0.2342] <>   [ans = 23.42 and scale == 'percent']

    :param prediction_strings:
    :param gold_ans_type:
    :param gold_scale:
    :param pred:
    :return:
    """
    if len(pred) > 1:
        return prediction_strings
    pred_str = str(pred[0])
    if pred_str is None:
        return prediction_strings
    if not pred_scale and '%' not in pred_str and is_number(pred_str): # mode only or no pred_scale num only
        pred_str = to_number(pred_str)
        if pred_str is None:
            return prediction_strings
        prediction_strings.append('%.4f' % pred_str)
    return prediction_strings


def em_f1(ground_truth: dict, prediction: Union[str, List], pred_scale="") -> Tuple[float, float]:
    """Exact match and F1 of one prediction, as computed in tag_op/tatqa_metric.py TaTQAEmAndF1.__call__."""
    if not prediction:
        exact_match = 0
        f1_score = 0
    else:
        gold_type, gold_answer, gold_scale = extract_gold_answers(ground_truth)
        if not gold_answer:
            exact_match = 0
            f1_score = 0
        else:
            ground_truth_answer_strings = get_answer_str(gold_answer, gold_scale)
            prediction = prediction if isinstance(prediction, list) else [prediction]
            prediction_strings = get_answer_str(prediction, pred_scale)
            prediction_strings = add_percent_pred(prediction_strings, pred_scale, prediction)
            exact_match, f1_score = metric_max_over_ground_truths(
                    get_metrics,
                    prediction_strings,
                    ground_truth_answer_strings
            )
            if gold_type in ['arithmetic', 'count']:
                """if gold type equals with arithmetic and count, set the f1_score == exact_match"""
                f1_score = exact_match
    return exact_match, f1_score
