import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { changePassword, getAccountHistory } from '../services/api';
import { useAuth } from '../context/AuthContext';

export const AccountPage: React.FC = () => {
  const { user, updateProfile, refreshUser } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState(user?.name ?? '');
  const [email, setEmail] = useState(user?.email ?? '');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [events, setEvents] = useState<Array<Record<string, unknown>>>([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!user) return;
    setName(user.name);
    setEmail(user.email);
    getAccountHistory()
      .then(setEvents)
      .catch(() => setError('Account history could not be loaded.'));
  }, [user]);

  const saveProfile = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    setMessage('');
    try {
      await updateProfile(name, email);
      setMessage('Profile updated.');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Profile update failed.');
    } finally {
      setSaving(false);
    }
  };

  const savePassword = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    setMessage('');
    try {
      await changePassword(currentPassword, newPassword);
      setMessage('Password changed. Your current session was revoked; sign in again.');
      setCurrentPassword('');
      setNewPassword('');
      await refreshUser();
      navigate('/login');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Password change failed.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="space-y-6">
      <header><h1 className="text-2xl font-bold font-mono text-slate-900">Profile &amp; Account History</h1><p className="mt-1 text-xs text-slate-500">Manage your account and review persisted activity.</p></header>
      {(error || message) && <p role={error ? 'alert' : 'status'} className={`rounded-lg p-3 text-xs ${error ? 'bg-rose-50 text-rose-800' : 'bg-emerald-50 text-emerald-800'}`}>{error || message}</p>}
      <div className="grid lg:grid-cols-2 gap-5">
        <form onSubmit={saveProfile} className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="text-sm font-semibold">Account profile</h2>
          <label className="block text-xs">Display name<input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} className="mt-1 w-full rounded-lg border border-slate-200 p-2" /></label>
          <label className="block text-xs">Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required maxLength={320} className="mt-1 w-full rounded-lg border border-slate-200 p-2" /></label>
          <p className="text-[11px] text-slate-500">Account created: {user?.createdAt ? new Date(user.createdAt).toLocaleString() : 'Unavailable'}</p>
          <button disabled={saving} className="rounded-lg bg-teal-700 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50">Save profile</button>
        </form>
        <form onSubmit={savePassword} className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="text-sm font-semibold">Change password</h2>
          <label className="block text-xs">Current password<input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required className="mt-1 w-full rounded-lg border border-slate-200 p-2" /></label>
          <label className="block text-xs">New password (at least 12 characters)<input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} minLength={12} required className="mt-1 w-full rounded-lg border border-slate-200 p-2" /></label>
          <button disabled={saving} className="rounded-lg border border-slate-300 px-4 py-2 text-xs font-semibold text-slate-700 disabled:opacity-50">Change password</button>
        </form>
      </div>
      <section className="rounded-xl border border-slate-200 bg-white">
        <div className="border-b border-slate-100 p-5"><h2 className="text-sm font-semibold">Account history</h2><p className="mt-1 text-xs text-slate-500">Events recorded since persistent activity tracking was enabled.</p></div>
        {events.length === 0 ? <p className="p-5 text-xs text-slate-500">No recorded account events.</p> : events.map((item, index) => (
          <article key={String(item.id ?? index)} className="border-b border-slate-100 p-4 last:border-0">
            <p className="text-xs font-semibold text-slate-800">{String(item.eventType ?? 'Activity').replaceAll('_', ' ')}</p>
            <p className="mt-1 text-xs text-slate-600">Outcome: {String(item.outcome ?? 'Unavailable')}</p>
            <p className="mt-1 text-[10px] text-slate-400">{item.createdAt ? new Date(String(item.createdAt)).toLocaleString() : 'Timestamp unavailable'}</p>
          </article>
        ))}
      </section>
    </main>
  );
};
