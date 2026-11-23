def toposort(graph):
    import heapq

    nodes = set(graph)
    for deps in graph.values():
        nodes.update(deps)
    dependencies = {node: set(graph.get(node, [])) for node in nodes}
    children = {node: [] for node in nodes}
    for node, deps in dependencies.items():
        for dep in deps:
            children[dep].append(node)
    ready = [node for node in nodes if not dependencies[node]]
    heapq.heapify(ready)
    result = []
    while ready:
        node = heapq.heappop(ready)
        result.append(node)
        for child in children[node]:
            dependencies[child].remove(node)
            if not dependencies[child]:
                heapq.heappush(ready, child)
    if len(result) != len(nodes):
        raise ValueError("cycle")
    return result
