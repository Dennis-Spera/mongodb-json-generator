import { useEffect, useState } from 'react';
import './CollectionsPanel.css';

export default function CollectionsPanel({ refresh }) {
  const [collections, setCollections] = useState([]);
  const [selected, setSelected] = useState(null);
  const [docs, setDocs] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchCollections();
  }, [refresh]);

  useEffect(() => {
    if (selected) fetchDocs(selected, 1);
  }, [selected]);

  async function fetchCollections() {
    try {
      const res = await fetch('/api/collections');
      const data = await res.json();
      setCollections(data.collections || []);
    } catch {
      setError('Backend not reachable.');
    }
  }

  async function fetchDocs(name, p = 1) {
    setLoading(true);
    try {
      const res = await fetch(`/api/collections/${name}?page=${p}&limit=20`);
      const data = await res.json();
      setDocs(data.docs);
      setTotal(data.total);
      setPage(p);
    } finally {
      setLoading(false);
    }
  }

  async function dropCollection(name) {
    if (!confirm(`Drop collection "${name}"? This cannot be undone.`)) return;
    await fetch(`/api/collections/${name}`, { method: 'DELETE' });
    setSelected(null);
    setDocs([]);
    fetchCollections();
  }

  const totalPages = Math.ceil(total / 20);

  return (
    <div className="collections-layout">
      <aside className="collections-sidebar">
        <h2 className="panel-title">Collections</h2>
        {error && <p className="status-err">{error}</p>}
        {collections.length === 0 && !error && (
          <p className="muted">No collections yet. Generate some data first.</p>
        )}
        {collections.map((c) => (
          <button
            key={c.name}
            className={`collection-item ${selected === c.name ? 'active' : ''}`}
            onClick={() => setSelected(c.name)}
          >
            <span className="col-name">{c.name}</span>
            <span className="tag">{c.count.toLocaleString()}</span>
          </button>
        ))}
      </aside>

      <div className="docs-panel">
        {selected ? (
          <>
            <div className="docs-header">
              <h2 className="panel-title">{selected}</h2>
              <div className="docs-actions">
                <span className="muted">{total.toLocaleString()} documents</span>
                <button className="btn-danger" onClick={() => dropCollection(selected)}>Drop</button>
              </div>
            </div>

            {loading ? (
              <p className="muted">Loading…</p>
            ) : (
              <pre>{JSON.stringify(docs, null, 2)}</pre>
            )}

            {totalPages > 1 && (
              <div className="pagination">
                <button className="btn-ghost" disabled={page === 1} onClick={() => fetchDocs(selected, page - 1)}>← Prev</button>
                <span className="muted">Page {page} / {totalPages}</span>
                <button className="btn-ghost" disabled={page === totalPages} onClick={() => fetchDocs(selected, page + 1)}>Next →</button>
              </div>
            )}
          </>
        ) : (
          <div className="docs-empty">
            <p className="muted">Select a collection to browse documents.</p>
          </div>
        )}
      </div>
    </div>
  );
}
