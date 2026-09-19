export function Arrow({ diagonal = false }: { diagonal?: boolean }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path
        d={diagonal ? "M6 18 18 6M6 6h12v12" : "M4 12h15m-6-6 6 6-6 6"}
        stroke="currentColor"
        strokeWidth="1.6"
      />
    </svg>
  );
}

export function Mark() {
  return (
    <svg
      width="30"
      height="32"
      viewBox="0 0 30 32"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M3 29V13h8v16M11 21V3h8v18M19 29V11h8v18"
        stroke="currentColor"
        strokeWidth="2.4"
      />
    </svg>
  );
}

export function Scene({ active }: { active: boolean }) {
  return (
    <div
      className={`scene ${active ? "scene-running" : ""}`}
      aria-hidden="true"
    >
      <div className="scene-orbit">
        <svg viewBox="0 0 650 440" fill="none">
          <g stroke="currentColor" strokeWidth="1">
            <path d="M70 270 280 390 584 214 374 92 70 270ZM70 246 280 366 584 190 374 68 70 246ZM70 222 280 342 584 166 374 44 70 222Z" />
            <path
              d="m70 222 0 48m210 72v48m304-224v48M374 44v48M122 192l210 121M173 162l210 120M223 134l210 120M274 103l210 121M324 74l210 121M123 252 427 75M175 282 479 105M227 312 531 135"
              opacity=".35"
            />
            <path
              d="m224 209 99 57 116-67-99-57-116 67Zm0-52 99 57 116-67-99-57-116 67Zm0 0v52m99 5v52m116-119v52"
              fill="var(--paper)"
            />
            <path
              d="m272 146 53 31 60-35-53-30-60 34Z"
              fill="var(--orange)"
              stroke="var(--orange)"
            />
            <path
              className="scene-signal"
              d="M128 249 197 209m241-7 90 51-104 61m-147-19-71 41M334 110V42l83-47"
              stroke="var(--orange)"
              strokeWidth="2"
            />
            <circle
              cx="128"
              cy="249"
              r="5"
              fill="var(--paper)"
              stroke="var(--orange)"
            />
            <circle
              cx="206"
              cy="336"
              r="5"
              fill="var(--paper)"
              stroke="var(--orange)"
            />
            <circle
              cx="424"
              cy="314"
              r="5"
              fill="var(--orange)"
              stroke="var(--orange)"
            />
          </g>
        </svg>
      </div>
      <span className="scene-label label-one">ISOLATED ENVIRONMENTS</span>
      <span className="scene-label label-two">
        <i /> PARALLEL BY DESIGN
      </span>
    </div>
  );
}
