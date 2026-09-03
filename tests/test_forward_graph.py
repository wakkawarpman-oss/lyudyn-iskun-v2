import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import ChannelForwardEdge
from database.repository import NetworkGraphRepository


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    ChannelForwardEdge.__table__.create(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_record_forward_edge_create_and_increment(db_session):
    repo = NetworkGraphRepository(db_session)
    
    # 1. Create first forward edge
    edge = repo.record_forward_edge("kpszsu", "kievreal1", "Повітряна тривога в Києві")
    assert edge is not None
    assert edge.source_channel == "kpszsu"
    assert edge.target_channel == "kievreal1"
    assert edge.forward_count == 1
    assert "Повітряна тривога" in edge.sample_post_text

    # 2. Increment existing edge
    edge_updated = repo.record_forward_edge("@KPSZSU", "@kievreal1", "Відбій тривоги")
    assert edge_updated.id == edge.id
    assert edge_updated.forward_count == 2
    assert "Відбій тривоги" in edge_updated.sample_post_text


def test_ignore_self_forward_and_empty(db_session):
    repo = NetworkGraphRepository(db_session)
    assert repo.record_forward_edge("kievreal1", "kievreal1") is None
    assert repo.record_forward_edge("", "kievreal1") is None
    assert repo.record_forward_edge("kpszsu", "") is None


def test_get_forward_graph_format(db_session):
    repo = NetworkGraphRepository(db_session)
    repo.record_forward_edge("kpszsu", "kievreal1")
    repo.record_forward_edge("kpszsu", "kievoperat")
    repo.record_forward_edge("dsns_telegram", "kievreal1")

    graph = repo.get_forward_graph(min_weight=1, limit=50, hours=24)
    assert "nodes" in graph
    assert "edges" in graph
    assert graph["total_nodes"] == 4
    assert graph["total_edges"] == 3

    # Check node attributes
    node_ids = {n["id"] for n in graph["nodes"]}
    assert "kpszsu" in node_ids
    assert "kievreal1" in node_ids
    assert "kievoperat" in node_ids
    assert "dsns_telegram" in node_ids


def test_get_top_forward_sources(db_session):
    repo = NetworkGraphRepository(db_session)
    # kpszsu: 3 forwards
    repo.record_forward_edge("kpszsu", "kievreal1")
    repo.record_forward_edge("kpszsu", "kievreal1")
    repo.record_forward_edge("kpszsu", "kievoperat")

    # dsns: 1 forward
    repo.record_forward_edge("dsns_telegram", "kievreal1")

    top = repo.get_top_forward_sources(limit=5, hours=24)
    assert len(top) == 2
    assert top[0]["source_channel"] == "kpszsu"
    assert top[0]["total_forwards"] == 3
    assert top[0]["amplifiers_count"] == 2
    assert top[1]["source_channel"] == "dsns_telegram"
    assert top[1]["total_forwards"] == 1


def test_channel_lineage(db_session):
    repo = NetworkGraphRepository(db_session)
    repo.record_forward_edge("kpszsu", "kievreal1")
    repo.record_forward_edge("kievreal1", "sub_channel")

    lineage = repo.get_channel_lineage("@kievreal1")
    assert lineage["channel"] == "kievreal1"
    assert len(lineage["sources"]) == 1
    assert lineage["sources"][0]["source"] == "kpszsu"
    assert len(lineage["amplifiers"]) == 1
    assert lineage["amplifiers"][0]["target"] == "sub_channel"
