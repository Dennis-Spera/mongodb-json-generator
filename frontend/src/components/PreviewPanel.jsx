import './PreviewPanel.css';

export default function PreviewPanel({ preview }) {
  return (
    <div className="preview-panel">
      <h2 className="panel-title">Preview</h2>
      {!preview && (
        <div className="preview-empty">
          <p>Click <strong>Preview</strong> to see generated documents here.</p>
        </div>
      )}
      {preview && (
        <pre>{JSON.stringify(preview, null, 2)}</pre>
      )}
    </div>
  );
}
