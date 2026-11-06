import { useState } from "react";
import type { Document, Profile } from "../lib/api";

export default function DocumentLibrary({
  documents,
  categories,
  loading,
}: {
  documents: Document[];
  categories: Profile["categories"];
  loading: boolean;
}) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const names = new Map(categories.map(({ id, name }) => [id, name]));
  const term = search.trim().toLowerCase();
  const visible = documents.filter(
    (doc) =>
      (!category || doc.category_id === category) &&
      [doc.title, doc.original_filename, names.get(doc.category_id) ?? ""].some(
        (value) => value.toLowerCase().includes(term),
      ),
  );

  return (
    <section className="library" aria-label="Document library" aria-busy={loading}>
      <div className="library-intro">
        <p className="eyebrow">DOCUMENT LIBRARY</p>
        <h2>Find a source</h2>
        <p className="muted">Browse and download PDFs available to your role.</p>
      </div>
      {documents.length > 0 && (
        <div className="library-controls">
          <label>
            <span>Search documents</span>
            <input
              type="search"
              placeholder="Title, filename or category"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <label>
            <span>Category</span>
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="">All categories</option>
              {categories.map(({ id, name }) => (
                <option value={id} key={id}>{name}</option>
              ))}
            </select>
          </label>
        </div>
      )}
      {loading ? (
        <p role="status" className="small">Loading documents…</p>
      ) : visible.length ? (
        <>
          <p className="small library-count" role="status">
            {visible.length} of {documents.length} documents
          </p>
          <div className="document-grid">
            {visible.map((doc) => (
              <a className="document-card" key={doc.id}
                href={`/api/v1/documents/${encodeURIComponent(doc.id)}/file`}
                target="_blank" rel="noopener noreferrer">
                <div className="document-card-top">
                  <span className="file-icon">PDF</span>
                  <span className="badge">{names.get(doc.category_id) ?? "Document"}</span>
                </div>
                <h2>{doc.title}</h2>
                <p>{doc.original_filename}</p>
                <span className="document-action">Download PDF <span aria-hidden="true">↓</span></span>
              </a>
            ))}
          </div>
        </>
      ) : (
        <div className="empty-library">
          <h2>{documents.length ? "No matching documents" : "No documents available yet"}</h2>
          {documents.length ? (
            <button className="secondary" onClick={() => { setSearch(""); setCategory(""); }}>
              Clear filters
            </button>
          ) : <p>Your administrator can publish documents for your role.</p>}
        </div>
      )}
    </section>
  );
}
