import { useState, useEffect } from 'react';
import './SchemaBuilder.css';

const FIELD_TYPES = [
  'firstName','lastName','fullName','email','phone','avatar','username','password',
  'street','city','state','country','zipCode','latitude','longitude',
  'productName','price','department',
  'companyName','jobTitle',
  'date','uuid','number','boolean','word','sentence','paragraph','color','url',
];

export default function SchemaBuilder({ schema, setSchema, setPreview, onSaved }) {
  const [fields, setFields] = useState([{ name: 'name', type: 'fullName' }]);
  const [count, setCount] = useState(10);
  const [collectionName, setCollectionName] = useState('my_collection');
  const [loading, setLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState(null);

  useEffect(() => {
    const s = {};
    fields.forEach((f) => { if (f.name) s[f.name] = f.type; });
    setSchema(s);
  }, [fields]);

  function addField() {
    setFields((prev) => [...prev, { name: '', type: 'word' }]);
  }

  function removeField(i) {
    setFields((prev) => prev.filter((_, idx) => idx !== i));
  }

  function updateField(i, key, val) {
    setFields((prev) => prev.map((f, idx) => idx === i ? { ...f, [key]: val } : f));
  }

  async function handlePreview() {
    setLoading(true);
    try {
      const res = await fetch('/api/generate/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schema, count: Math.min(count, 5) }),
      });
      const data = await res.json();
      setPreview(data.docs);
    } catch {
      setPreview({ error: 'Backend not reachable. Start the backend server.' });
    } finally {
      setLoading(false);
    }
  }

  async function handleSave() {
    setLoading(true);
    setSaveStatus(null);
    try {
      const res = await fetch('/api/generate/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schema, count, collectionName }),
      });
      const data = await res.json();
      setSaveStatus(`✓ Inserted ${data.inserted} documents into "${data.collectionName}"`);
      onSaved();
    } catch {
      setSaveStatus('✗ Save failed — is the backend running?');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="schema-builder">
      <h2 className="panel-title">Schema Builder</h2>

      <div className="field-list">
        {fields.map((field, i) => (
          <div key={i} className="field-row">
            <input
              placeholder="field name"
              value={field.name}
              onChange={(e) => updateField(i, 'name', e.target.value)}
            />
            <select value={field.type} onChange={(e) => updateField(i, 'type', e.target.value)}>
              {FIELD_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <button className="btn-danger remove-btn" onClick={() => removeField(i)}>×</button>
          </div>
        ))}
      </div>

      <button className="btn-ghost add-btn" onClick={addField}>+ Add Field</button>

      <div className="options-row">
        <div className="option-group">
          <label>Count</label>
          <input
            type="number"
            min={1}
            max={1000}
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
          />
        </div>
        <div className="option-group">
          <label>Collection name</label>
          <input
            value={collectionName}
            onChange={(e) => setCollectionName(e.target.value)}
            placeholder="collection_name"
          />
        </div>
      </div>

      {saveStatus && (
        <p className={saveStatus.startsWith('✓') ? 'status-ok' : 'status-err'}>{saveStatus}</p>
      )}

      <div className="action-row">
        <button className="btn-ghost" onClick={handlePreview} disabled={loading}>
          {loading ? 'Loading…' : 'Preview (5 docs)'}
        </button>
        <button className="btn-primary" onClick={handleSave} disabled={loading || !collectionName}>
          {loading ? 'Saving…' : `Save ${count} docs →`}
        </button>
      </div>
    </div>
  );
}
