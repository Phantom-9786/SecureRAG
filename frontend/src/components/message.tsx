import type { Message } from "../lib/api";
export default function MessageView({ message }: { message: Message }) {
  return (
    <article className={`message ${message.role}`}>
      <div className="message-avatar" aria-hidden="true">
        {message.role === "user" ? "Y" : "◈"}
      </div>
      <div className="message-body">
        <div className="message-meta">
          <strong>{message.role === "user" ? "You" : "SecureRAG"}</strong>
          <time dateTime={message.created_at}>
            {new Date(message.created_at).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </time>
        </div>
        <p className={message.withheld ? "answer-text muted" : "answer-text"}>
          {message.content}
        </p>
        {message.sources.length ? (
          <section aria-label="Answer sources">
            <h2 className="source-heading">Sources · {message.sources.length}</h2>
            <div className="source-list">
              {message.sources.map((source) => (
                <a
                  className="source-card"
                  key={source.source_id}
                  href={`/api/v1/documents/${encodeURIComponent(source.document_id)}/file`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <span className="source-label">
                    [{source.source_id}] · PDF · PAGE {source.page_number}
                  </span>
                  <strong>{source.document_title}</strong>
                  <span>Download PDF ↓</span>
                </a>
              ))}
            </div>
          </section>
        ) : null}
      </div>
    </article>
  );
}
