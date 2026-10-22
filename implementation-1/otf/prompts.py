"""Generic prompts. Nothing here names a domain: the document describes itself through its own intro text
and the Navigation Map's structure."""

QUESTION_TYPES = ("descriptive", "explanatory", "predictive", "counterfactual")

# First router (used in the "OTF single pass" run). Replaced on 2026-10-22 after dev-set comparison:
# pilot20 with gpt-oss, 293/308 for this prompt vs 305/308 for ROUTER below.
ROUTER_V1 = """Classify the question into exactly one type:
- descriptive: asks for a fact that is stated in the document or can be read or counted from it (what, which, how many, is there).
- explanatory: asks why something happened, or what caused or is responsible for an outcome.
- predictive: asks what will happen next or later, beyond the period the document records.
- counterfactual: asks what would happen if some condition were different, for example if something were removed or absent.
Reply with only JSON: {"type": "<one of: descriptive, explanatory, predictive, counterfactual>"}"""

# Frozen router (2026-10-22), chosen on pilot20 only (2 variants tried).
ROUTER = """Classify the question by what it asks you to work out. Decide with these checks, IN THIS ORDER, and stop at the first that applies:
1. counterfactual: the question supposes a condition different from what was recorded and asks about its consequences. Signs: "if ... were removed / absent / not present", "without ...", "had ... not happened", "what would happen if".
2. predictive: the question asks what will happen next or later, after the period the document records. Signs: "what will happen next", "which event will happen", "after ... ends".
3. explanatory: the question asks for the cause of a recorded outcome, i.e. what produced it or what it depended on. Signs: "why", "what caused", "what led to", "responsible for", "because of". This holds also when the question lists candidate causes to choose from ("which of the following is responsible for ...").
4. descriptive: otherwise. The question asks about the recorded facts themselves: what is there, which one, how many, what property, whether something happened.
The answer format (open question or list of choices) does not decide the type; the wording of the question does.
Reply with only JSON: {"type": "<one of: descriptive, explanatory, predictive, counterfactual>"}"""

GENERATOR_SYSTEM ="""You write Python code that turns a document's recorded data into an executable model. \
The code runs in a sandbox: allowed imports are math, json, re, itertools, collections, statistics, functools, \
heapq, bisect, dataclasses, typing, numpy, fractions, decimal, copy, operator. No file, network or process access. \
Reply with one ```python code block and nothing else."""

DOC_CONTEXT = """DOCUMENT DESCRIPTION (the document's own front matter):
{intro}

NAVIGATION MAP SCHEMA (the document is available to your code as `doc`, a dict):
doc = {{"nodes": [{{"node_id", "title", "level", "parent_id", "children": [node_ids], "pages": [first, last],
                  "kind": "table" | "list" | "text",
                  "table": {{"columns": [...], "rows": [[cell strings], ...]}}   (kind == table)
                  "lines": [line strings]                                     (kind == list)
                  "text": str }}]}}                                          (kind == text)
Top-level nodes that have children are SCOPES (independent units of the document); a question names its scope by title.
Helpers already defined: node_by_title(doc, title), children(doc, node), scope_nodes(doc, scope) -> child nodes of the scope.
{schema}
"""

PARSERS_USER = """{context}
STEP 1 OF 2. WRITE THESE FUNCTIONS (all values JSON-serialisable; `scope` is a scope title string):

def entities(doc, scope) -> list of {{"id": str, "description": str}}
    Every distinct entity that appears in the scope, with its full human-readable description.
    The ids are the identifiers every other function uses for these entities.

def recorded_end(doc, scope) -> float
    The last time point covered by the scope's records (in the document's own time unit).

def observed_events(doc, scope) -> list of {{"time": float, "kind": str, "participants": [entity ids]}}
    Every interaction event (an event involving two or more entities) recorded for the scope, in time
    order, in the same time unit as recorded_end. Participants must be ids returned by entities().

HOW IT IS CHECKED: on a few scopes the three functions must run, return entities, find the recorded
interactions, use only ids from entities(), and give times between 0 and recorded_end.
{feedback}"""

SIMULATOR_USER = """{context}
These functions are ALREADY WRITTEN AND CHECKED (they will be placed above your code; call them freely):
```python
{parsers}
```
WHAT THEY RETURN on the example scope '{example_scope}' (use exactly these ids and this time unit):
entities = {example_entities}
recorded_end = {example_end}
observed_events = {example_events}

STEP 2 OF 2. WRITE THIS FUNCTION (plus any helpers it needs; do not redefine the functions above):

def simulate(doc, scope, removed=(), horizon=None, start=0.0) -> list of {{"time": float, "kind": str, "participants": [entity ids]}}
    A FORWARD MODEL of the process recorded in the scope, run from time `start` to `horizon`.
    Initialise every entity present at `start` from its latest recorded state at or before `start`
    (advancing it to `start` if that record is earlier); an entity that first appears after `start` enters
    at the time and in the state of its first record. Then advance all states in small time steps, detect
    the interaction events yourself, and update the states when an interaction happens. Return only the
    interaction events after `start`. Never read recorded events, or recorded states later than `start`
    (other than an entity's first records): the model must run under conditions that were never recorded.
    `removed`: ids of entities that are absent for the whole run. `horizon`: run until this time
    (default recorded_end); times after recorded_end are predictions. Use the same ids and time unit as
    observed_events.
    Estimate unknown constants (sizes, thresholds, rates such as gradual slowing, how states change in an
    interaction) from the recorded data; you may use the full records of ALL scopes for that (for example
    the states recorded at the times of recorded interactions in other scopes).
    HOW IT IS CHECKED: for a few scopes, `start` is set just before the scope's first recorded interaction
    and simulate is called on a copy of the document in which that scope keeps only its records up to
    `start` (plus each entity's first two table rows) and no list line mentioning two or more entities
    (other scopes are untouched). The interaction events it returns must match the scope's recorded
    interactions after `start` (same participants, close in time). Copying recorded events cannot pass.
{feedback}"""

AGENT_SYSTEM = """You write Python code that turns a document's recorded data into an executable model, and you \
can run code on the document's data before you commit. Code runs in a sandbox: allowed imports are math, json, re, \
itertools, collections, statistics, functools, heapq, bisect, dataclasses, typing, numpy, fractions, decimal, copy, \
operator. No file, network or process access.
Every reply must contain fenced code, either:
```explore
...  # a script that investigates the data: `doc` and the already-written functions are available;
     # print() what you want to see (you will get the printed output back, truncated)
```
or, when you are ready, the final answer:
```python
...  # simulate() and any helpers
```"""

EXPLORE_HOWTO = """
BEFORE WRITING simulate, INVESTIGATE THE DATA. You may run up to {n_explore} ```explore blocks; the functions
above (and the helpers) are available inside them. Measure what the model needs, for example: how each recorded
quantity changes between consecutive records of one entity (and how that relates to any recorded rates, which
gives the time unit), how quickly things slow down, the states of the participants at the recorded times of
interactions (for example the distance between them), and how states change across an interaction. Use other
scopes than the checked ones if you like. Then reply with the final ```python block."""

EXPLORE_OUTPUT = """OUTPUT of your explore block ({left} explore runs left):
{output}"""

CHECK_FAILED = """YOUR simulate FAILED THE CHECK ({left_submits} submissions left, {left_explore} explore runs left).
Check result: {report}
Investigate with ```explore if useful, then submit a corrected complete ```python block."""

FEEDBACK = """
YOUR PREVIOUS ATTEMPT (shown below) FAILED THE CHECK. Fix it.
Check result: {report}
Previous code:
```python
{code}
```"""

ARGS = """Which entities does this question remove, take away, or treat as absent? Use the entity list.
ENTITIES:
{entities}
QUESTION:
{question}
Reply with only JSON: {{"removed": [entity ids]}}  (an empty list if none)"""

ANSWER = {
    "descriptive": "Answer from the document sections below (the question's scope).",
    "explanatory": "Answer using the recorded events and the dependency table below. In the table, removing an "
                   "entity from the start and re-running a model of the process makes the listed events disappear. "
                   "An event is responsible for an outcome when the outcome would not have happened without it.",
    "predictive": "Answer using the events the model predicts after the recorded period ends (listed below), "
                  "together with the recorded events.",
    "counterfactual": "Answer using the counterfactual run below: a model of the process re-run with the "
                      "removed entities absent from the start. Statements about events that appear in the "
                      "counterfactual run are true; events that do not appear in it would not happen.",
}
