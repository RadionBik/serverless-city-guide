"""LangGraph wiring: intake → plan → gather → narrate → verify → reply."""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent import nodes
from agent.state import AgentState


def build_graph() -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    g = StateGraph(AgentState)

    g.add_node("intake", nodes.intake)
    g.add_node("plan", nodes.plan)
    g.add_node("gather", nodes.gather)
    g.add_node("narrate", nodes.narrate)
    g.add_node("verify", nodes.verify)
    g.add_node("reply", nodes.reply)

    g.set_entry_point("intake")
    g.add_edge("intake", "plan")
    g.add_edge("plan", "gather")
    g.add_edge("gather", "narrate")
    g.add_edge("narrate", "verify")
    g.add_conditional_edges("verify", nodes.route, {"retry": "gather", "reply": "reply"})
    g.add_edge("reply", END)

    return g.compile()
