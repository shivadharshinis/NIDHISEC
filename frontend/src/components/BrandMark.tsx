export default function BrandMark({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="#3a5aa8" />
      <path
        d="M16 6l8 3v6c0 5.2-3.4 9.3-8 11-4.6-1.7-8-5.8-8-11V9l8-3z"
        fill="none"
        stroke="#fff"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path
        d="M12.5 16l2.5 2.5 4.5-5"
        fill="none"
        stroke="#fff"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
