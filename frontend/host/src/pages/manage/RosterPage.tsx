import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Upload } from 'lucide-react';
import { api } from '../../lib/api';
import { Button } from '../../components/ui/button';
import { Card, CardContent, CardHeader } from '../../components/ui/card';

interface RosterEntry {
  id: number;
  netid: string;
  full_name: string;
  email: string;
  is_active: boolean;
  imported_at: string;
}

interface UploadResult {
  imported: number;
  updated: number;
  deactivated: number;
  errors: string[];
}

type Mode = 'add_update' | 'replace';

export default function RosterPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const [entries, setEntries] = useState<RosterEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [mode, setMode] = useState<Mode>('add_update');
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function load() {
    try {
      setEntries(await api.get<RosterEntry[]>(`/host/courses/${courseId}/roster`));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load roster');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    setError('');
    setResult(null);
    void load();
  }, [courseId]);

  async function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (fileRef.current) fileRef.current.value = '';
    if (!file) return;
    if (
      mode === 'replace' &&
      !confirm(
        'Replace the roster? Every student who is not in this file will be deactivated ' +
          'and can no longer join through the roster.',
      )
    ) {
      return;
    }
    setUploading(true);
    setError('');
    setResult(null);
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('mode', mode);
      setResult(await api.postForm<UploadResult>(`/host/courses/${courseId}/roster`, form));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  }

  const active = entries.filter((e) => e.is_active);
  const inactive = entries.filter((e) => !e.is_active);

  return (
    <div className="p-8 max-w-4xl space-y-6">
      <h2 className="text-2xl font-bold text-slate-100">Roster</h2>

      <Card>
        <CardHeader>
          <h3 className="font-semibold text-slate-100">Upload</h3>
          <p className="text-slate-400 text-sm">Upload the gradebook CSV exported from Canvas.</p>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as Mode)}
              className="rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="add_update">Add / update only</option>
              <option value="replace">Replace roster (deactivate students not in the file)</option>
            </select>
            <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={upload} />
            <Button size="sm" onClick={() => fileRef.current?.click()} disabled={uploading}>
              <Upload size={14} className="mr-1" />
              {uploading ? 'Uploading…' : 'Choose CSV'}
            </Button>
          </div>
          {result && (
            <div className="text-sm">
              <p className="text-slate-200">
                {result.imported} added · {result.updated} updated · {result.deactivated} deactivated
              </p>
              {result.errors.length > 0 && (
                <ul className="mt-2 list-disc pl-5 text-amber-400">
                  {result.errors.map((msg, i) => <li key={i}>{msg}</li>)}
                </ul>
              )}
            </div>
          )}
          {error && <p className="text-red-400 text-sm">{error}</p>}
        </CardContent>
      </Card>

      {loading ? (
        <p className="text-slate-400">Loading…</p>
      ) : (
        <>
          <RosterTable title={`Active (${active.length})`} entries={active} />
          {inactive.length > 0 && <RosterTable title={`Inactive (${inactive.length})`} entries={inactive} muted />}
        </>
      )}
    </div>
  );
}

function RosterTable({ title, entries, muted }: { title: string; entries: RosterEntry[]; muted?: boolean }) {
  return (
    <Card>
      <CardHeader><h3 className="font-semibold text-slate-100">{title}</h3></CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-slate-400 text-sm">No students.</p>
        ) : (
          <table className={`w-full text-sm ${muted ? 'text-slate-500' : 'text-slate-200'}`}>
            <thead>
              <tr className="text-left text-slate-400">
                <th className="py-1 pr-4 font-medium">Name</th>
                <th className="py-1 pr-4 font-medium">NetID</th>
                <th className="py-1 font-medium">Email</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} className="border-t border-slate-700">
                  <td className="py-1.5 pr-4">{e.full_name}</td>
                  <td className="py-1.5 pr-4 font-mono">{e.netid}</td>
                  <td className="py-1.5">{e.email}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}
