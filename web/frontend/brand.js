const BRAND = {
    logo: `
        <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
                <linearGradient id="slab-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#1c1c22" />
                    <stop offset="100%" stop-color="#101014" />
                </linearGradient>
                <linearGradient id="molten-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#ff5312" />
                    <stop offset="100%" stop-color="#ff9a1f" />
                </linearGradient>
                <filter id="glow">
                    <feGaussianBlur stdDeviation="1.2" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                </filter>
            </defs>
            <!-- Slab -->
            <path d="M11 7 L41 5.5 L37.5 41 L7.5 42.5 Z" fill="url(#slab-grad)" stroke="#2a2a33" stroke-width="1" />
            <!-- Ticks -->
            <g stroke="#6f9bff" stroke-width="1.2">
                <line x1="9.5" y1="15" x2="12.5" y2="15" />
                <line x1="9" y1="22" x2="12" y2="22" />
                <line x1="8.5" y1="29" x2="11.5" y2="29" />
                <line x1="8" y1="36" x2="11" y2="36" />
            </g>
            <!-- Molten Seam -->
            <path d="M15 13 L25 23 L19.5 29 L33 37" stroke="url(#molten-grad)" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" filter="url(#glow)">
                <animate attributeName="opacity" values="0.78;1;0.78" dur="3.2s" repeatCount="indefinite" />
            </path>
        </svg>
    `,
    heroForge: `
        <svg viewBox="0 0 200 120" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
                <linearGradient id="gauge-molten" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stop-color="#ff5312" />
                    <stop offset="100%" stop-color="#ff9a1f" />
                </linearGradient>
            </defs>
            <!-- Arc Background -->
            <path d="M20 100 A 80 80 0 0 1 180 100" stroke="#24242c" stroke-width="12" fill="none" stroke-linecap="round" />
            <!-- Arc Filled -->
            <path d="M20 100 A 80 80 0 0 1 140 40" stroke="url(#gauge-molten)" stroke-width="12" fill="none" stroke-linecap="round" />
            <!-- Ticks -->
            <g stroke="#6f9bff" stroke-width="1">
                <line x1="100" y1="20" x2="100" y2="30" />
                <line x1="35" y1="65" x2="45" y2="70" />
                <line x1="165" y1="65" x2="155" y2="70" />
            </g>
            <!-- Needle -->
            <line x1="100" y1="100" x2="140" y2="45" stroke="#ece6dc" stroke-width="3" stroke-linecap="round" />
            <!-- Center Axis -->
            <circle cx="100" cy="100" r="6" fill="#101014" stroke="#ff6a24" stroke-width="2" />
        </svg>
    `,
    favicon: `
        <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="48" height="48" rx="9" fill="#08080a" />
            <g transform="scale(0.8) translate(6, 6)">
                <path d="M11 7 L41 5.5 L37.5 41 L7.5 42.5 Z" fill="#1c1c22" stroke="#2a2a33" stroke-width="1" />
                <path d="M15 13 L25 23 L19.5 29 L33 37" stroke="#ff6a24" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
            </g>
        </svg>
    `
};
