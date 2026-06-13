import { useState } from 'react';
import SchemaBuilder from './components/SchemaBuilder.jsx';
import PreviewPanel from './components/PreviewPanel.jsx';
import CollectionsPanel from './components/CollectionsPanel.jsx';
import './App.css';

export default function App() {
  const [tab, setTab] = useState('generator');
  const [preview, setPreview] = useState(null);
  const [schema, setSchema] = useState({});
  const [refreshCollections, setRefreshCollections] = useState(0);

  function onSaved() {
    setRefreshCollections((n) => n + 1);
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-logo">
          <span className="logo-icon">⚡</span>
          <span>MongoDB JSON Generator</span>
        </div>
        <nav className="app-nav">
          <button
            className={tab === 'generator' ? 'nav-btn active' : 'nav-btn'}
            onClick={() => setTab('generator')}
          >
            Generator
          </button>
          <button
            className={tab === 'collections' ? 'nav-btn active' : 'nav-btn'}
            onClick={() => setTab('collections')}
          >
            Collections
          </button>
        </nav>
      </header>

      <main className="app-main">
        {tab === 'generator' ? (
          <div className="generator-layout">
            <SchemaBuilder
              schema={schema}
              setSchema={setSchema}
              setPreview={setPreview}
              onSaved={onSaved}
            />
            <PreviewPanel preview={preview} />
          </div>
        ) : (
          <CollectionsPanel refresh={refreshCollections} />
        )}
      </main>
    </div>
  );
}
