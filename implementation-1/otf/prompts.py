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
Helpers already defined: node_by_title(doc, title), node_by_id(doc, node_id), children(doc, node),
scope_nodes(doc, scope) -> child nodes of the scope, table_rows(node) -> [(row_index, {{column: cell}})]
(table_rows builds new dicts on every call, so identify a row by its row_index, never with `is`).
A LOCATION says where a record was read from: [node_id, row_index] (a whole table row),
[node_id, row_index, [column names]] (some cells of a row) or [node_id, line_index] (a list line).
{schema}
"""

PARSERS_USER = """{context}
STEP 1 OF 2. WRITE THESE READING FUNCTIONS (all values JSON-serialisable; `scope` is a scope title string).
They separate what the records GIVE the process from what the process PRODUCES.

def entities(doc, scope) -> list of {{"id": str, "description": str}}
    Every distinct entity the scope's records are about, with its full human-readable description.
    The ids are the identifiers every other function uses for these entities.

def recorded_end(doc, scope) -> float or None
    The last time point covered by the scope's records, in the document's own time unit.
    None if the records have no time (for example a table of figures).

def inputs(doc, scope) -> list of {{"id": str, "time": float or None, "kind": str, "entities": [entity ids],
                                   "fields": {{name: number or str}}, "src": [locations]}}
    Everything that enters the process from outside and is not caused by it: entities arriving and the state
    they arrive in (for an entity present from the start, its first record or records), external requests or
    events, amounts supplied from outside, figures that are given rather than computed from other figures,
    and records of future inputs (planned or scheduled ones). Recorded states that change because of the
    process are NOT inputs. Give each input a unique id.

def outcomes(doc, scope) -> list of {{"time": float or None, "kind": str, "entities": [entity ids],
                                     "value": number or None, "src": [locations]}}
    Everything the process produces: every recorded event that results from the process (not the arrival of
    an input), with "value": None, and every recorded result quantity (levels, amounts done, figures computed
    from other figures), with its number as "value". An event may involve any number of entities.

def params(doc, scope) -> {{name: number}}      (optional; omit it if the document states no constants)
    Constants the document states (limits, capacities, rates), by a short name.

`src` lists every location the record was read from, including the cells that give its time and its entities
(an input and an outcome may share such cells, for example the time cell of one row).
HOW IT IS CHECKED: on a few scopes the functions must run, use only ids from entities(), give outcome times
within the recorded period, and point `src` at real rows, columns and lines. Then a copy of the scope is made
in which the outcomes are hidden (their cells and lines, and every timed row or line after the first outcome
that no input was read from; hidden cells become empty strings "" and hidden rows and lines are removed): on
that copy inputs() must return exactly the same records, and outcomes() must find almost none of the hidden
ones. Value-less records that only occur at regularly spaced times (for example one record per entity at every
sample time) mark that a row exists, not something the process produces: the check ignores them, so return the
events the process produces and the result quantities with their values.
{feedback}"""

SIMULATOR_USER = """{context}
These functions are ALREADY WRITTEN AND CHECKED (they will be placed above your code; call them freely):
```python
{parsers}
```
WHAT THEY RETURN on the example scope '{example_scope}' (use exactly these ids, kinds and this time unit):
entities = {example_entities}
recorded_end = {example_end}
inputs = {example_inputs}
outcomes = {example_outcomes}
params = {example_params}

STEP 2 OF 2. WRITE THIS FUNCTION (plus any helpers it needs; do not redefine the functions above):

def simulate(doc, scope, inputs, params, start=None, horizon=None) -> list of outcome records
    A FORWARD MODEL of the process recorded in the scope. It is given the exogenous inputs (`inputs`, a list
    like the one inputs() returns, possibly changed by the caller to ask what-if questions: read the given
    inputs ONLY from this argument, never from the document) and the constants (`params`, possibly changed),
    and runs from time `start` to `horizon` (default recorded_end; later times are predictions).
    Initialise the state at `start` from the latest records at or before `start`; where those do not fully
    determine the state, rebuild it by running your model from an earlier point, keeping recorded values
    where they exist. Then apply the process's rules in time order (small time steps, or event by event,
    whichever the process needs). Implement exactly any rules the document states in its front matter, and
    estimate the rest (sizes, thresholds, rates, how states change at an outcome) from the recorded data; you
    may use the full records of ALL scopes for that. An entity takes part only if it has at least one input.
    Return the outcome records (same kinds, ids, time unit and value meaning as outcomes()) after `start`.
    If recorded_end is None (no time), `start` and `horizon` are None: compute every outcome from the inputs.
    HOW IT IS CHECKED: for a few scopes, `start` is set just before the scope's first recorded outcome and
    simulate is called on a copy of the document in which that scope's outcomes after `start` are hidden
    (hidden cells are empty strings "", hidden rows and lines are removed; the inputs are kept; other scopes
    are untouched). The outcomes it returns must match the hidden ones
    (same kind, same entities, close in time and value). Copying recorded outcomes cannot pass, and a model
    that ignores `inputs` fails.
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
above (and the helpers) are available inside them. Measure what the model needs, for example: which rules the
document states, and whether the records follow them (test a stated rule on a few recorded cases); how each
recorded quantity changes between consecutive records of one entity, and how fast it changes on its own; the
recorded states of the entities involved at the times of recorded outcomes (for example how far apart they
are, or how much of a limit is used); and how states change at an outcome. Use other scopes than the checked
ones if you like. Then reply with the final ```python block."""

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

PATCH = """A question supposes that something was different from what the records show. Write that change as
patches on the recorded inputs or constants.
ENTITIES:
{entities}
EXAMPLE INPUT OF EACH KIND:
{examples}
CONSTANTS: {params}
TIME: {time}
QUESTION:
{question}
Patch operations (S selects inputs: {{"entity": id, "kind": k, "time": t, "from": t1, "to": t2}}, every key
except "entity" optional; selecting only an entity selects all of its inputs):
  {{"op": "remove", "select": S}}                                   the selected inputs never happen
  {{"op": "set", "select": S, "field": F, "value": V}}              a field of the selected inputs gets value V
  {{"op": "scale", "select": S, "field": F, "factor": X}}           a field is multiplied by X
  {{"op": "shift", "select": S, "by": D}}                           the selected inputs happen D time units later
  {{"op": "add", "record": {{"time": t, "kind": k, "entities": [ids], "fields": {{...}}}}}}   an extra input
  {{"op": "set" or "scale", "param": NAME, "value" or "factor": ..., "from": T}}   a constant changes (from time T)
Something "removed", "absent" or "never there" removes all inputs of that entity.
Reply with only JSON: {{"patches": [ ... ]}}  (an empty list if the question supposes no change)"""

CAUSES = """A question asks what an outcome depended on, and lists candidate causes. For each candidate, write
the change that takes that cause away, as patches on the recorded inputs, so that the outcome can be re-run
without it.
ENTITIES:
{entities}
EXAMPLE INPUT OF EACH KIND:
{examples}
RECORDED OUTCOMES (numbered):
{outcomes}
QUESTION AND CANDIDATES:
{question}
Patch operations as in: {{"op": "remove", "select": S}}, {{"op": "set", "select": S, "field": F, "value": V}},
{{"op": "scale", ...}}, {{"op": "shift", ...}}; S = {{"entity": id, "kind": k, "time": t, "from": t1, "to": t2}}.
Reply with only JSON: {{"target": <number of the outcome the question is about>,
 "choices": {{"<choice number>": [patches] or null}}}}
Use null when a candidate is not something that can be taken away by changing inputs (for example another
outcome)."""

RECORD_AND_TOOL = ("Below are the document's own sections for this scope, then a TOOL RESULT computed with a model "
                   "of the process. Take recorded facts and figures from the sections; take what the model computes "
                   "(a forecast, or what changes under a hypothetical change) from the tool result. Where the tool result "
                   "cannot check something (for example a condition it cannot take away), decide it from the "
                   "sections.")

ANSWER = {
    "descriptive": "Answer from the document sections below (the question's scope).",
    "explanatory": "Answer using the recorded outcomes, the dependency table and the choice checks below. In the "
                   "table, taking an entity's inputs away and re-running a model of the process (checked against "
                   "the record) makes the listed outcomes disappear. A choice check re-runs the process with and without "
                   "that cause and applies the difference to the record. Something is responsible for an outcome when the outcome would not have happened "
                   "without it.",
    "predictive": "Answer using the outcomes the model predicts after the recorded period ends (listed below), run "
                  "forward from the last recorded states and the document's own future inputs, if any, together with "
                  "the recorded outcomes.",
    "counterfactual": "Answer using the counterfactual run below: the record is kept until the change can first "
                      "matter; from there a model of the process, checked against the record, is run twice, with and "
                      "without the change, and only what differs between the two runs is applied to the record. "
                      "Outcomes in the counterfactual run happen; recorded outcomes that are not in it would not "
                      "happen. DIFFERENCES lists what the change alters.",
}
