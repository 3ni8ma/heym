import type { AgentMemoryEdgeDTO, AgentMemoryNodeDTO } from "@/types/agentMemory";

/** Whitespace-separated terms, all of which must match (AND). Empty query = no filtering. */
export function parseSearchTokens(query: string): string[] {
  return query.trim().toLowerCase().split(/\s+/).filter((token) => token.length > 0);
}

function stringifyPropertyValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return "";
    }
  }
  return String(value);
}

/** Name, type, and every attribute key/value, newline-joined so a term can't span two fields. */
function searchableTextForNode(node: AgentMemoryNodeDTO): string {
  const parts: string[] = [node.entity_name, node.entity_type];
  const properties = node.properties;
  if (properties && typeof properties === "object") {
    for (const [key, value] of Object.entries(properties)) {
      parts.push(key, stringifyPropertyValue(value));
    }
  }
  return parts.join("\n").toLowerCase();
}

function nodeMatchesSearch(node: AgentMemoryNodeDTO, tokens: string[]): boolean {
  if (tokens.length === 0) {
    return true;
  }
  const haystack = searchableTextForNode(node);
  return tokens.every((token) => haystack.includes(token));
}

/** Relationship type plus any relationship property key/value (for example `status`). */
function searchableTextForEdge(edge: AgentMemoryEdgeDTO): string {
  const parts: string[] = [edge.relationship_type];
  const properties = edge.properties;
  if (properties && typeof properties === "object") {
    for (const [key, value] of Object.entries(properties)) {
      parts.push(key, stringifyPropertyValue(value));
    }
  }
  return parts.join("\n").toLowerCase();
}

function edgeMatchesSearch(edge: AgentMemoryEdgeDTO, tokens: string[]): boolean {
  if (tokens.length === 0) {
    return true;
  }
  const haystack = searchableTextForEdge(edge);
  return tokens.every((token) => haystack.includes(token));
}

export interface MemoryGraphSearchResult {
  visibleNodeIds: Set<string>;
  visibleEdgeIds: Set<string>;
}

/**
 * An entity hit brings its whole neighbourhood: every relationship it takes part in and the
 * entity on the far side of each. A relationship hit brings only the two entities it joins and
 * stops there — searching a relation type is a question about that relation, so the ends' own
 * other relationships are not part of the answer.
 */
export function searchMemoryGraph(
  nodes: AgentMemoryNodeDTO[],
  edges: AgentMemoryEdgeDTO[],
  tokens: string[],
): MemoryGraphSearchResult {
  if (tokens.length === 0) {
    return {
      visibleNodeIds: new Set(nodes.map((n) => n.id)),
      visibleEdgeIds: new Set(edges.map((e) => e.id)),
    };
  }

  const hitNodeIds = new Set<string>();
  for (const node of nodes) {
    if (nodeMatchesSearch(node, tokens)) {
      hitNodeIds.add(node.id);
    }
  }

  const visibleNodeIds = new Set(hitNodeIds);
  const visibleEdgeIds = new Set<string>();
  for (const edge of edges) {
    const expandsFromEntityHit =
      hitNodeIds.has(edge.source_node_id) || hitNodeIds.has(edge.target_node_id);
    if (!expandsFromEntityHit && !edgeMatchesSearch(edge, tokens)) {
      continue;
    }
    visibleEdgeIds.add(edge.id);
    visibleNodeIds.add(edge.source_node_id);
    visibleNodeIds.add(edge.target_node_id);
  }

  // A relationship between two entities that are both on screen is worth drawing even when
  // neither end was a hit (both arrived as neighbours of one).
  for (const edge of edges) {
    if (visibleNodeIds.has(edge.source_node_id) && visibleNodeIds.has(edge.target_node_id)) {
      visibleEdgeIds.add(edge.id);
    }
  }

  return { visibleNodeIds, visibleEdgeIds };
}
