"""Every newly authored instruction of the Tier B baselines (ReAct-R, ReAct-C, ReCode, GraphRAG), in one place.

tests/test_no_benchmark_words.py scans this file: method instructions must stay domain-agnostic. The shared answer
contract, document content (front matter, section titles) and question text are inserted at run time and are
not part of the method, so they are outside the guard.

Candidate slots (SPEC sec. 11 tuning budget, at most 3 per method, chosen on pilot20 only):
  1  default implementation and prompts
  2  explicit generic tool-use instructions
  3  concise evidence and final-answer instructions
GraphRAG uses slot 2 for concise evidence/final-answer text and slot 3 for its own pilot-only prompt auto-tuning.
"""

SLOTS = (1, 2, 3)

# ---------------------------------------------------------------- ReAct (both variants)
REACT_SYSTEM = {
    1: ("Answer the question by alternating between reasoning and actions: think about what you need, call a "
        "tool, read its observation, and repeat. When you know the answer, call finish with the answer JSON."),
    2: ("Answer the question by alternating between reasoning and actions. A reliable way to work:\n"
        "1. Call list_sections to see the document's outline and find the part the question is about.\n"
        "2. Call list_sections with that node's id, then read_section on the nodes that hold the evidence. "
        "Read the evidence instead of guessing.\n"
        "3. Use search when the outline does not show where the evidence is.\n"
        "{code_step}"
        "Then call finish with exactly the answer JSON."),
    3: ("Answer the question by alternating between reasoning and actions. Gather only the evidence the question "
        "needs, keep each reasoning step short, and stop as soon as the evidence is sufficient. The argument of "
        "finish must be exactly the answer JSON and nothing else."),
}
REACT_CODE_STEP = ("4. When the answer needs counting, ordering, arithmetic or projecting values forward, write "
                   "Python with the python tool over the parsed map `doc` and print the result.\n")
FRONT_MATTER = "DOCUMENT FRONT MATTER (the document's own description of its contents):\n{front}"

TOOL_DOCS = {
    "list_sections": ("Table of contents. Without node_id: the top-level nodes. With node_id: that node's "
                      "children. Each line gives node id, title and pages."),
    "read_section": "The full content of one node of the outline, by node id.",
    "search": "The k passages of the document most similar to the query (embedding search).",
    "finish": "Submit the final answer: the JSON object required by the answer format. Ends the task.",
    "python": ("Run Python in a sandbox and return what it prints (20 s limit). Available: `doc`, the document's "
               "parsed Navigation Map, a dict whose 'nodes' list holds node_id, title, level, parent_id, pages, "
               "children, kind ('table', 'list' or 'text') and the content in 'table' {'columns', 'rows'}, "
               "'lines' or 'text'; helpers node_by_title(doc, title), children(doc, node), "
               "scope_nodes(doc, title). Allowed imports: {modules}. No file or network access."),
}

# ---------------------------------------------------------------- ReCode
RECODE_ACTIONS = {
    1: ("- search[<query>]: the 5 passages of the document most similar to <query>.\n"
        "- list_sections[<node id>]: the outline. With an empty id, the top-level nodes; with a node id, its "
        "children. Each line gives node id, title and pages.\n"
        "- read_section[<node id>]: the full content of one node.\n"
        "- answer[<json>]: submit the final answer, the JSON object required by the instruction. Ends the task.\n"
        "Your code also has these Python variables: `doc`, the document's parsed Navigation Map (a dict whose "
        "'nodes' list holds node_id, title, level, parent_id, pages, children, kind and the content in 'table' "
        "{'columns', 'rows'}, 'lines' or 'text'), and the helpers node_by_title(doc, title), children(doc, node), "
        "scope_nodes(doc, title). Code may import only: {modules}."),
}
RECODE_ACTIONS[2] = RECODE_ACTIONS[1] + (
    "\nA reliable way to work: find the part of the document the question is about in the outline, read the "
    "nodes that hold the evidence, compute over `doc` when the answer needs counting, ordering, arithmetic or "
    "projecting values forward, then call answer.")
RECODE_ACTIONS[3] = RECODE_ACTIONS[1] + (
    "\nGather only the evidence the question needs and submit with answer as soon as it is sufficient; the "
    "answer argument must be exactly the required JSON object.")

# Two generic examples. The {placeholders} are filled from pilot20 (the dev set) only: a question prompt, the
# document's own front matter and outline, and node ids/titles of that question's part of the document.
RECODE_FEWSHOTS = """INPUT:
The current function to expand is:
solve(instruction, observation)
The variables you can use is:
- instruction (str): {instruction}
- observation (str): {observation}

OUTPUT:
<think>
The question names one part of the document. I will find that part in the outline, read the nodes that hold the
evidence, work out the answer from them, and submit it in the required JSON format.
</think>
<execute>
node_ids = find_relevant_nodes(instruction, observation)
evidence = read_evidence(node_ids)
answer_json = derive_answer(instruction, evidence)
run("answer[" + answer_json + "]")
</execute>



INPUT:
The current function to expand is:
node_ids = find_relevant_nodes(instruction, observation)
The variables you can use is:
- instruction (str): {instruction}
- observation (str): {observation}

OUTPUT:
<think>
The question names "{scope_title}". In the outline that is node {scope_id}; listing its children shows which nodes
hold the evidence.
</think>
<execute>
children_list = run("list_sections[{scope_id}]")
node_ids = [line.split(" | ")[0] for line in children_list.splitlines() if line.strip()]
</execute>
"""

# ---------------------------------------------------------------- GraphRAG (local search)
GRAPHRAG_LOCAL_EXTRA = {
    1: "",
    2: ("\n\nUse only the evidence in the data tables that bears on the question, keep any explanation brief, and "
        "end your response with exactly the JSON object required by the answer instructions below."),
    3: "",
}
GRAPHRAG_ANSWER_HEADER = "\n\n---Answer instructions---\n\n"
GRAPHRAG_RESPONSE_TYPE = "A single JSON object in the format given by the answer instructions"
