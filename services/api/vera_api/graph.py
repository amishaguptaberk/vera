"""LangGraph workflow graph built from data, checkpointed in Postgres.

The graph only holds the run's position; nodes call `node_fn`, which goes through the
SpecialistRunner and gateway commands. thread_id is the run id, so a restarted worker resumes
from the last checkpoint and completed nodes are not run again. The checkpointer tables are
created by migration 0004, not here.
"""

import operator
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

NodeFn = Callable[[str, str, dict[str, Any]], dict[str, Any] | None]  # (key, kind, state)


class RunState(TypedDict):
    run_id: str
    completed: Annotated[list[str], operator.add]


# Example workflow as data: two parallel specialists, then a join.
TEST_WORKFLOW: dict[str, Any] = {
    "id": "test-parallel-join",
    "nodes": [
        {"key": "charge", "kind": "specialist"},
        {"key": "related", "kind": "specialist"},
        {"key": "review", "kind": "join"},
    ],
    "edges": [
        ["__start__", "charge"],
        ["__start__", "related"],
        ["charge", "review"],
        ["related", "review"],
        ["review", "__end__"],
    ],
}


def plain_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def postgres_checkpointer(database_url: str) -> Iterator[PostgresSaver]:
    with PostgresSaver.from_conn_string(plain_url(database_url)) as saver:
        yield saver


def build_graph(
    workflow_def: dict[str, Any], node_fn: NodeFn, checkpointer: PostgresSaver | None = None
) -> Any:
    graph = StateGraph(RunState)
    keys = {n["key"] for n in workflow_def["nodes"]}

    def wrap(key: str, kind: str) -> Callable[[Any], dict[str, Any]]:
        def run(state: Any) -> dict[str, Any]:
            update = node_fn(key, kind, dict(state)) or {}
            return {**update, "completed": [key]}

        return run

    for node in workflow_def["nodes"]:
        graph.add_node(node["key"], wrap(node["key"], node["kind"]))  # type: ignore[call-overload]
    incoming: dict[str, list[str]] = defaultdict(list)
    for src, dst in workflow_def["edges"]:
        for end in (src, dst):
            if end not in keys and end not in ("__start__", "__end__"):
                raise ValueError(f"edge references unknown node {end!r}")
        incoming[END if dst == "__end__" else dst].append(START if src == "__start__" else src)
    for dst, sources in incoming.items():
        if len(sources) > 1 and dst != END and START not in sources:
            graph.add_edge(sources, dst)  # join: wait for every parallel branch
        else:
            for src in sources:
                graph.add_edge(src, dst)
    return graph.compile(checkpointer=checkpointer)


def run_graph(graph: Any, run_id: str) -> dict[str, Any]:
    """Start the run, or resume it from its checkpoint when one exists."""
    config = {"configurable": {"thread_id": run_id}}
    if graph.get_state(config).created_at is not None:
        result = graph.invoke(None, config)
    else:
        result = graph.invoke({"run_id": run_id, "completed": []}, config)
    return dict(result)
