"use client";
import { useState, type FormEvent } from "react";
import { api } from "../../lib/api";
import type { AdminOptions, ManagedDocument } from "../../lib/admin";
import type { AdminAction } from "./panel";

export default function DocumentsAdmin({
  documents,
  options,
  run,
  busy,
}: {
  documents: ManagedDocument[];
  options: AdminOptions;
  run: AdminAction;
  busy: boolean;
}) {
  const [validation, setValidation] = useState("");
  const [search, setSearch] = useState("");
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidation("");
    const form = event.currentTarget;
    const data = new FormData(form);
    const file = data.get("file");
    if (
      !(file instanceof File) ||
      !file.size ||
      !file.name.toLowerCase().endsWith(".pdf")
    ) {
      setValidation("Select a non-empty PDF file.");
      return;
    }
    if (file.size > options.max_upload_mb * 1024 * 1024) {
      setValidation(`PDF must be at most ${options.max_upload_mb} MB.`);
      return;
    }
    const done = await run(async (me) => {
      await api("/admin/documents", {
        method: "POST",
        csrf: me.csrf_token,
        form: data,
      });
    }, "PDF uploaded and indexed. It is now active for users with category access.");
    if (done) form.reset();
  }
  const filtered = documents.filter((doc) =>
    `${doc.title} ${doc.original_filename}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  return (
    <div className="admin-section">
      <form className="admin-card admin-form" onSubmit={upload}>
        <h3>Upload a document</h3>
        <p className="small">
          Text-based PDFs up to {options.max_upload_mb} MB. Successful uploads
          become active after indexing. Scanned PDFs need a text layer.
        </p>
        {validation ? (
          <p role="alert" className="error">
            {validation}
          </p>
        ) : null}
        <fieldset disabled={busy || !options.categories.length}>
          <div className="admin-form-grid">
            <label>
              Document title
              <input
                name="title"
                required
                maxLength={255}
                placeholder="e.g. Engineering onboarding guide"
              />
            </label>
            <label>
              Category
              <select
                aria-label="Category"
                name="category_id"
                required
                defaultValue=""
              >
                <option value="" disabled>
                  Choose a category
                </option>
                {options.categories.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="wide">
              PDF file
              <input
                name="file"
                type="file"
                accept="application/pdf,.pdf"
                required
              />
            </label>
          </div>
          <button className="primary" type="submit">
            Upload & index PDF
          </button>
        </fieldset>
      </form>
      <div className="admin-card">
        <div className="admin-list-heading">
          <h3>
            Documents <span className="count">{documents.length}</span>
          </h3>
          <label className="search-label">
            Search documents
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Title or filename"
            />
          </label>
        </div>
        {filtered.length ? (
          <div className="table-scroll">
            <table>
              <caption className="sr-only">
                Documents and ingestion status
              </caption>
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Category</th>
                  <th>Indexing</th>
                  <th>Visibility</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((doc) => (
                  <tr key={doc.id}>
                    <td>
                      <strong>{doc.title}</strong>
                      <small>{doc.original_filename}</small>
                    </td>
                    <td>
                      {options.categories.find(
                        (item) => item.id === doc.category_id,
                      )?.name ?? "Unknown category"}
                    </td>
                    <td>
                      <span className={`status-pill ${doc.ingestion_status}`}>
                        {doc.ingestion_status}
                      </span>
                    </td>
                    <td>{doc.active ? "Active" : "Inactive"}</td>
                    <td>
                      <button
                        className="secondary"
                        disabled={busy || doc.ingestion_status !== "ready"}
                        onClick={() =>
                          void run(
                            async (me) => {
                              await api(`/admin/documents/${doc.id}`, {
                                method: "PATCH",
                                csrf: me.csrf_token,
                                body: { active: !doc.active },
                              });
                            },
                            doc.active
                              ? "Document deactivated. It is no longer eligible for retrieval or download."
                              : "Document activated.",
                          )
                        }
                      >
                        {doc.active ? "Deactivate" : "Activate"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="small">
            {documents.length
              ? "No documents match your search."
              : "No documents uploaded yet."}
          </p>
        )}
        <p className="small">
          Processing and failed documents cannot be activated. Refresh for the
          latest state. Original downloads remain subject to your own category
          access in the document library.
        </p>
      </div>
    </div>
  );
}
