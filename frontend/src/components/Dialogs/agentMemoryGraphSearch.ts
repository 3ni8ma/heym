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
  /** Entities whose own text matched, plus both ends of every relationship that matched. */
  visibleNodeIds: Set<string>;
  /** Relationships between two visible entities — everything else is unrelated to the query. */
  visibleEdgeIds: Set<string>;
}

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

  const visibleNodeIds = new Set<string>();
  for (const node of nodes) {
    if (nodeMatchesSearch(node, tokens)) {
      visibleNodeIds.add(node.id);
    }
  }
  for (const edge of edges) {
    if (edgeMatchesSearch(edge, tokens)) {
      visibleNodeIds.add(edge.source_node_id);
      visibleNodeIds.add(edge.target_node_id);
    }
  }

  const visibleEdgeIds = new Set<string>();
  for (const edge of edges) {
    if (visibleNodeIds.has(edge.source_node_id) && visibleNodeIds.has(edge.target_node_id)) {
      visibleEdgeIds.add(edge.id);
    }
  }

  return { visibleNodeIds, visibleEdgeIds };
}
