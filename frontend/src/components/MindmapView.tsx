import * as d3 from "d3";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Document, MindmapResponse } from "../api/types";
import DocumentDetail from "./DocumentDetail";

const RELATION_COLOR: Record<string, string> = {
  semantic: "#3b6fd9",
  shared_tag: "#e0a13b",
};

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  title: string;
  source_type: string;
  isCenter: boolean;
}

export default function MindmapView() {
  const [searchParams, setSearchParams] = useSearchParams();
  const centerId = searchParams.get("doc");
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<{ id: string; title: string }[]>([]);
  const [mindmap, setMindmap] = useState<MindmapResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<Document[]>([]);
  const svgRef = useRef<SVGSVGElement>(null);

  // Selecting a node (click) no longer jumps straight to an action — with
  // many related articles the small, crowded circles make a precise
  // double-click or "click = recenter" unreliable. Instead selection opens
  // a fixed-position panel (full title, not the truncated graph label) with
  // explicit buttons, so the target you act on is always a big stationary
  // button rather than the tiny node itself.
  const [selectedNode, setSelectedNode] = useState<
    { id: string; title: string; source_type: string } | null
  >(null);
  const [openDoc, setOpenDoc] = useState<Document | null>(null);
  const [openDocLoading, setOpenDocLoading] = useState(false);
  const [openDocError, setOpenDocError] = useState<string | null>(null);

  async function handleOpenArticle() {
    if (!selectedNode) return;
    setOpenDocLoading(true);
    setOpenDocError(null);
    try {
      const doc = await api.getDocument(selectedNode.id);
      setOpenDoc(doc);
    } catch (e) {
      setOpenDocError(e instanceof Error ? e.message : "找不到這份文件");
    } finally {
      setOpenDocLoading(false);
    }
  }

  function handleRecenter() {
    if (!selectedNode) return;
    setSearchParams({ doc: selectedNode.id });
    setSelectedNode(null);
  }

  useEffect(() => {
    if (centerId) return;
    api
      .listDocuments({ limit: 8 })
      .then((res) => setRecent(res.items))
      .catch(() => setRecent([]));
  }, [centerId]);

  useEffect(() => {
    if (!centerId) {
      setMindmap(null);
      return;
    }
    setError(null);
    api
      .getMindmap(centerId)
      .then(setMindmap)
      .catch((e) => setError(e.message || "找不到這份文件"));
  }, [centerId]);

  useEffect(() => {
    if (query.trim().length < 2) {
      setSuggestions([]);
      return;
    }
    const handle = setTimeout(() => {
      api
        .search(query.trim(), 6)
        .then((res) =>
          setSuggestions(
            res.results.map((r) => ({ id: r.id, title: (r.payload.title as string) || r.id }))
          )
        )
        .catch(() => setSuggestions([]));
    }, 300);
    return () => clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    setSelectedNode(null);
  }, [mindmap?.center_id]);

  useEffect(() => {
    if (!mindmap || !svgRef.current) return;

    const width = svgRef.current.clientWidth || 800;
    const height = 560;

    const nodes: SimNode[] = mindmap.nodes.map((n) => ({
      id: n.id,
      title: n.title || n.id.slice(0, 8),
      source_type: n.source_type,
      isCenter: n.id === mindmap.center_id,
    }));
    const nodeById = new Map(nodes.map((n) => [n.id, n]));
    const links = mindmap.edges
      .filter((e) => nodeById.has(e.source) && nodeById.has(e.target))
      .map((e) => ({ ...e }));

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const g = svg.append("g");

    svg.call(
      d3
        .zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.3, 3])
        .on("zoom", (event) => g.attr("transform", event.transform))
    );

    const simulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink(links as d3.SimulationLinkDatum<SimNode>[])
          .id((d: any) => d.id)
          .distance(110)
      )
      .force("charge", d3.forceManyBody().strength(-260))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide(34));

    const link = g
      .append("g")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", (d) => RELATION_COLOR[d.relation_type] ?? "#999")
      .attr("stroke-width", (d) => 1 + d.score * 3)
      .attr("stroke-opacity", 0.6);

    const node = g
      .append("g")
      .selectAll<SVGGElement, SimNode>("g")
      .data(nodes)
      .join("g")
      .style("cursor", "pointer")
      .call(
        d3
          .drag<SVGGElement, SimNode>()
          .on("start", (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      )
      .on("click", (_event, d) => {
        setSelectedNode({ id: d.id, title: d.title, source_type: d.source_type });
      });

    node
      .append("circle")
      .attr("class", "mindmap-node-circle")
      .attr("r", (d) => (d.isCenter ? 16 : 10))
      .attr("fill", (d) => (d.isCenter ? "#3b6fd9" : "#8b93a7"))
      .attr("stroke", "#fff")
      .attr("stroke-width", 1.5);

    node
      .append("text")
      .text((d) => (d.title.length > 18 ? d.title.slice(0, 18) + "…" : d.title))
      .attr("x", 0)
      .attr("y", (d) => (d.isCenter ? 30 : 22))
      .attr("text-anchor", "middle")
      .attr("font-size", 11)
      .attr("fill", "var(--text)");

    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y);
      node.attr("transform", (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => {
      simulation.stop();
    };
  }, [mindmap, setSearchParams]);

  // Highlights the selected node's circle in place (no simulation restart)
  // so it's obvious which node the floating panel below refers to — matters
  // most exactly when many nodes are crowded together and look alike.
  useEffect(() => {
    if (!svgRef.current) return;
    d3.select(svgRef.current)
      .selectAll<SVGCircleElement, SimNode>(".mindmap-node-circle")
      .attr("stroke", (d) => (d.id === selectedNode?.id ? "#e0a13b" : "#fff"))
      .attr("stroke-width", (d) => (d.id === selectedNode?.id ? 3 : 1.5));
  }, [selectedNode, mindmap]);

  return (
    <div>
      <div style={{ position: "relative", maxWidth: 360, marginBottom: 14 }}>
        <input
          placeholder="搜尋文件作為中心節點…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ width: "100%" }}
        />
        {suggestions.length > 0 && (
          <div className="card" style={{ position: "absolute", top: "100%", left: 0, right: 0, zIndex: 10, padding: 4 }}>
            {suggestions.map((s) => (
              <button
                key={s.id}
                onClick={() => {
                  setSearchParams({ doc: s.id });
                  setQuery("");
                  setSuggestions([]);
                }}
                style={{ display: "block", width: "100%", textAlign: "left", border: "none", background: "none" }}
              >
                {s.title}
              </button>
            ))}
          </div>
        )}
      </div>

      {!centerId && (
        <div>
          <p className="muted" style={{ fontSize: 13, marginBottom: 8 }}>
            搜尋文件，或從下面挑一份最近的文件，作為關聯圖的中心節點：
          </p>
          {recent.length === 0 ? (
            <p className="muted">知識庫還沒有文件。</p>
          ) : (
            recent.map((doc) => (
              <div
                key={doc.id}
                className="card"
                style={{ marginBottom: 8, cursor: "pointer" }}
                onClick={() => setSearchParams({ doc: doc.id })}
              >
                <div style={{ fontWeight: 600, fontSize: 13 }}>
                  {doc.title || doc.id.slice(0, 8)}
                </div>
                <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                  {doc.source_type} · {doc.created_at.slice(0, 10)}
                </div>
              </div>
            ))
          )}
        </div>
      )}
      {error && <p style={{ color: "var(--danger)" }}>{error}</p>}

      {centerId && (
        <div style={{ position: "relative" }}>
          <svg
            ref={svgRef}
            width="100%"
            height={560}
            style={{ border: "1px solid var(--border)", borderRadius: 8 }}
          />

          {selectedNode && (
            <div
              className="card"
              style={{
                position: "absolute",
                top: 12,
                right: 12,
                maxWidth: 280,
                padding: 12,
                boxShadow: "0 2px 10px rgba(0,0,0,0.15)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{selectedNode.title}</div>
                <button
                  onClick={() => setSelectedNode(null)}
                  style={{ border: "none", background: "none", cursor: "pointer", padding: 0 }}
                >
                  ✕
                </button>
              </div>
              <div className="muted" style={{ fontSize: 12, margin: "4px 0 10px" }}>
                {selectedNode.source_type}
              </div>
              {openDocError && (
                <p style={{ color: "var(--danger)", fontSize: 12 }}>{openDocError}</p>
              )}
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <button onClick={handleOpenArticle} disabled={openDocLoading}>
                  {openDocLoading ? "開啟中…" : "開啟文章內容"}
                </button>
                <button onClick={handleRecenter}>以此為中心重新檢視關聯</button>
              </div>
            </div>
          )}
        </div>
      )}

      {openDoc && <DocumentDetail doc={openDoc} onClose={() => setOpenDoc(null)} />}
    </div>
  );
}
