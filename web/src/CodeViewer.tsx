import { loader, Editor } from '@monaco-editor/react';
import * as monaco from 'monaco-editor/editor/editor.api.js';
import 'monaco-editor/languages/definitions/python/register.js';
import 'monaco-editor/languages/definitions/ruby/register.js';
import editorWorker from 'monaco-editor/editor/editor.worker.js?worker';

self.MonacoEnvironment = { getWorker: () => new editorWorker() };
loader.config({ monaco });

interface CodeViewerProps {
  height: string;
  language: 'python' | 'ruby';
  value: string;
}

export default function CodeViewer({ height, language, value }: CodeViewerProps) {
  return <Editor
    height={height}
    language={language}
    theme="vs-dark"
    value={value}
    options={{
      readOnly: true,
      minimap: { enabled: false },
      fontSize: 12,
      scrollBeyondLastLine: false,
      wordWrap: 'on',
      padding: { top: 15 },
    }}
  />;
}
