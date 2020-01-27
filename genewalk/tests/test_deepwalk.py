from networkx import MultiGraph
from genewalk.deepwalk import DeepWalk, get_neighbors_probs


def test_run_walks():
    mg = MultiGraph()
    mg.add_edge('a', 'b')
    mg.add_edge('b', 'c')
    dw = DeepWalk(mg, 10, 100)
    dw.get_walks(workers=1)
    # Number of neighbors for all nodes together is 4, times niter: 400
    assert len(dw.walks) == 400, len(dw.walks)
    assert len([w for w in dw.walks if w[0] == 'a']) == 100
    assert len([w for w in dw.walks if w[0] == 'b']) == 200

    dw.get_walks(workers=2)
    # Number of neighbors for all nodes together is 4, times niter: 400
    assert len(dw.walks) == 400, len(dw.walks)
    assert len([w for w in dw.walks if w[0] == 'a']) == 100
    assert len([w for w in dw.walks if w[0] == 'b']) == 200


def test_neighbors_probs():
    mg = MultiGraph()
    edges = [('a', 'b'), ('b', 'c'), ('a', 'c'), ('c', 'd'), ('d', 'e')]
    for edge in edges:
        mg.add_edge(*edge)

    neighbors, probs = get_neighbors_probs(mg, 'a', None, 1, 1)
    assert neighbors == ['b', 'c']
    assert list(probs) == [0.5, 0.5]

    neighbors, probs = get_neighbors_probs(mg, 'b', 'a', 1, 1)
    assert neighbors == ['a', 'c']
    assert list(probs) == [0.5, 0.5]

    neighbors, probs = get_neighbors_probs(mg, 'b', 'a', 1/3, 1/5)
    assert neighbors == ['a', 'c']
    assert list(probs) == [0.75, 0.25], probs

    neighbors, probs = get_neighbors_probs(mg, 'c', 'b', 1/3, 1/5)
    assert neighbors == ['b', 'a', 'd'], neighbors
    assert list(probs) == [3/9, 1/9, 5/9], probs
