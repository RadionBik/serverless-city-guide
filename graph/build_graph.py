# graph/build_graph.py (shape, not final code)
from langgraph.graph import StateGraph, END
from graph.state import AgentState
from graph.nodes import intake, planner, gather, narrate, verify, reply

def build_graph():
    g = StateGraph(AgentState)

    g.add_node("intake", intake.run)
    g.add_node("planner", planner.run)
    g.add_node("gather", gather.run)
    # g.add_node("load_profile", ...)
    g.add_node("narrate", narrate.run)
    g.add_node("verify", verify.run)
    g.add_node("reply", reply.run)

    g.set_entry_point("intake")
    g.add_edge("intake", "planner")
    g.add_edge("planner", "gather")
    g.add_edge("gather", "narrate")
    g.add_edge("narrate", "verify")

    g.add_conditional_edges(
        "verify",
        verify.route,          # returns "retry" or "reply"
        {"retry": "gather", "reply": "reply"},
    )
    g.add_edge("reply", END)

    return g.compile()