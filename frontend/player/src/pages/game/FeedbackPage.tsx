import { ThemeToggle } from '../../components/ThemeToggle';

export default function FeedbackPage() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 gap-6 text-center pt-16">
      <ThemeToggle className="fixed top-3 right-3 z-40" />
      <div className="text-6xl">🔒</div>
      <p className="text-slate-100 text-2xl font-bold">Answer locked in!</p>
      <div className="flex justify-center mt-2">
        <div className="w-8 h-8 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
      <p className="text-slate-400 text-sm">Waiting for host to reveal results…</p>
    </div>
  );
}
