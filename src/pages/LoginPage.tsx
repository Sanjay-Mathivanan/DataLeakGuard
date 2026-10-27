import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { ShieldAlert, Lock, Mail, ArrowRight, CheckCircle2, Eye, EyeOff } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const { login } = useAuth();
  const { success, error } = useToast();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      error('Authentication Error', 'Please provide email and password.');
      return;
    }

    setIsLoading(true);
    try {
      await login(email, password);
      success('Authentication Successful', 'Welcome to DataLeakGuard-CV console.');
      navigate('/dashboard');
    } catch (err: any) {
      error('Login Failed', err?.message || 'Invalid credentials.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col lg:flex-row text-slate-900">
      {/* Left Column: Project Identity & Statement */}
      <div className="lg:w-1/2 p-8 lg:p-16 flex flex-col justify-between border-b lg:border-b-0 lg:border-r border-slate-200 bg-white">
        <div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-teal-50 border border-teal-200 flex items-center justify-center text-teal-700">
              <ShieldAlert className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight font-mono text-slate-900">
                DataLeakGuard<span className="text-teal-600">-CV</span>
              </h1>
              <p className="text-xs text-slate-500">Evidence-Based Integrity Assurance</p>
            </div>
          </div>

          <div className="mt-16 max-w-lg">
            <span className="text-xs font-mono font-semibold uppercase tracking-wider text-teal-700">
              Assurance Architecture
            </span>
            <h2 className="text-3xl lg:text-4xl font-extrabold tracking-tight text-slate-900 mt-2 text-balance leading-tight">
              Evidence-based integrity assurance for trustworthy ML pipelines.
            </h2>
            <p className="text-sm text-slate-600 mt-4 leading-relaxed">
              Profile tabular datasets, inspect persisted leakage findings and evidence, and review
              approved repair, quarantine, and combined-cleaning operations.
            </p>

            <div className="mt-8 space-y-3">
              <div className="flex items-center gap-2.5 text-xs text-slate-700">
                <CheckCircle2 className="w-4 h-4 text-teal-600 shrink-0" />
                <span>Five implemented, column-configurable tabular leakage detectors</span>
              </div>
              <div className="flex items-center gap-2.5 text-xs text-slate-700">
                <CheckCircle2 className="w-4 h-4 text-teal-600 shrink-0" />
                <span>Persistent findings, evidence, and operation history</span>
              </div>
              <div className="flex items-center gap-2.5 text-xs text-slate-700">
                <CheckCircle2 className="w-4 h-4 text-teal-600 shrink-0" />
                <span>Approved repair and quarantine with hash-verified output downloads</span>
              </div>
              <div className="flex items-center gap-2.5 text-xs text-slate-700">
                <CheckCircle2 className="w-4 h-4 text-teal-600 shrink-0" />
                <span>Combined exact-duplicate cleanup on a separate output copy</span>
              </div>
            </div>
          </div>
        </div>

      </div>

      {/* Right Column: Login Card */}
      <div className="lg:w-1/2 p-6 sm:p-12 lg:p-16 flex items-center justify-center bg-[#F8FAFC]">
        <div className="w-full max-w-md bg-white border border-slate-200 rounded-2xl p-8 shadow-xs">
          <div className="mb-6">
            <h3 className="text-xl font-bold text-slate-900 font-mono">Operator Sign In</h3>
            <p className="text-xs text-slate-500 mt-1">
              Enter your authorized credentials to access the integrity console.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1.5">
                Email
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="analyst@domain.com"
                  className="w-full pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-lg text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:border-teal-600 focus:ring-1 focus:ring-teal-600 transition-colors"
                />
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-xs font-medium text-slate-700">
                  Password
                </label>
                <span className="text-[11px] text-slate-400">Password recovery is not available</span>
              </div>
              <div className="relative">
                <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full pl-9 pr-10 py-2 bg-white border border-slate-200 rounded-lg text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:border-teal-600 focus:ring-1 focus:ring-teal-600 transition-colors"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  className="absolute right-3 top-2.5 p-0.5 text-slate-400 hover:text-slate-600 focus:outline-none"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-2.5 px-4 rounded-lg bg-teal-700 hover:bg-teal-800 disabled:opacity-50 text-white text-xs font-semibold flex items-center justify-center gap-2 transition-colors mt-2 shadow-xs cursor-pointer"
            >
              {isLoading ? (
                <span>Authenticating...</span>
              ) : (
                <>
                  <span>Login</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          <div className="mt-6 pt-6 border-t border-slate-100 text-center">
            <p className="text-xs text-slate-500">
              Don't have an account?{' '}
              <Link to="/register" className="text-teal-700 hover:underline font-semibold">
                Register
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
