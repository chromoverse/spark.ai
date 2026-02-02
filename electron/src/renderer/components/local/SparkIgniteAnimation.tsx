import React, { useState, useEffect } from "react";
import styled from "styled-components";

const SparkIgniteAnimation = () => {
  const [stage, setStage] = useState("dot");

  useEffect(() => {
    // Stage 1: Dot grows to full size (0-2s)
    const timer1 = setTimeout(() => setStage("grown"), 100);

    // Stage 2: Text appears (2-3s)
    const timer2 = setTimeout(() => setStage("text-appears"), 2100);

    // Stage 3: Icon moves left (3-4s)
    const timer3 = setTimeout(() => setStage("displaced"), 3100);

    // Stage 4: Icon eats text and returns center (5-6s)
    const timer4 = setTimeout(() => setStage("merge"), 5000);

    return () => {
      clearTimeout(timer1);
      clearTimeout(timer2);
      clearTimeout(timer3);
      clearTimeout(timer4);
    };
  }, []);

  return (
    <StyledWrapper>
      <div className="animation-container">
        <div className={`icon-wrapper stage-${stage}`}>
          <div className="loader">
            <svg width={100} height={100} viewBox="0 0 100 100">
              <defs>
                <mask id="clipping">
                  <polygon points="0,0 100,0 100,100 0,100" fill="black" />
                  <polygon points="25,25 75,25 50,75" fill="white" />
                  <polygon points="50,25 75,75 25,75" fill="white" />
                  <polygon points="35,35 65,35 50,65" fill="white" />
                  <polygon points="35,35 65,35 50,65" fill="white" />
                  <polygon points="35,35 65,35 50,65" fill="white" />
                  <polygon points="35,35 65,35 50,65" fill="white" />
                </mask>
              </defs>
            </svg>
            <div className="box" />
          </div>
        </div>

        <div className={`text-wrapper stage-${stage}`}>
          <span className="spark-text">SPARK</span>
        </div>
      </div>
    </StyledWrapper>
  );
};

const StyledWrapper = styled.div`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  min-height: 200px;

  .animation-container {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 500px;
    height: 150px;
  }

  /* ICON ANIMATIONS */
  .icon-wrapper {
    position: absolute;
    left: 50%;
    transform: translateX(-50%) scale(0);
    transition: all 2s cubic-bezier(0.34, 1.56, 0.64, 1);
    z-index: 10;
  }

  .icon-wrapper.stage-dot {
    transform: translateX(-50%) scale(0);
  }

  .icon-wrapper.stage-grown {
    transform: translateX(-50%) scale(1);
  }

  .icon-wrapper.stage-text-appears {
    transform: translateX(-50%) scale(1);
  }

  .icon-wrapper.stage-displaced {
    transform: translateX(-200%) scale(1);
    transition: all 1s cubic-bezier(0.68, -0.55, 0.265, 1.55);
  }

  .icon-wrapper.stage-merge {
    transform: translateX(-50%) scale(0.75);
    transition: all 1.2s cubic-bezier(0.68, -0.55, 0.265, 1.55);
  }

  /* TEXT ANIMATIONS */
  .text-wrapper {
    position: absolute;
    left: 50%;
    transform: translateX(calc(50px + 5px)) scale(0);
    opacity: 0;
    transition: all 1s cubic-bezier(0.34, 1.56, 0.64, 1);
  }

  .text-wrapper.stage-dot,
  .text-wrapper.stage-grown {
    transform: translateX(calc(50px + 5px)) scale(0);
    opacity: 0;
  }

  .text-wrapper.stage-text-appears {
    transform: translateX(calc(50px + 5px)) scale(1);
    opacity: 1;
  }

  .text-wrapper.stage-displaced {
    transform: translateX(calc(50px + 5px)) scale(1);
    opacity: 1;
  }

  .text-wrapper.stage-merge {
    transform: translateX(calc(50px + 5px)) scale(0.3);
    opacity: 0;
    transition: all 1s ease-in;
  }

  .spark-text {
    font-size: 64px;
    font-weight: 800;
    color: #475569;
    letter-spacing: 12px;
    font-family: system-ui, -apple-system, sans-serif;
    text-transform: uppercase;
    display: inline-block;
    transition: all 1s ease;
  }

  .stage-merge .spark-text {
    font-size: 32px;
    letter-spacing: 2px;
  }

  .loader {
    --color-one: #ffbf48;
    --color-two: #be4a1d;
    --color-three: #ffbf4780;
    --color-four: #bf4a1d80;
    --color-five: #ffbf4740;
    --time-animation: 2s;
    --size: 1;
    position: relative;
    border-radius: 50%;
    transform: scale(var(--size));
    box-shadow: 0 0 25px 0 var(--color-three), 0 20px 50px 0 var(--color-four);
    animation: colorize calc(var(--time-animation) * 3) ease-in-out infinite;
  }

  .loader::before {
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    width: 100px;
    height: 100px;
    border-radius: 50%;
    border-top: solid 1px var(--color-one);
    border-bottom: solid 1px var(--color-two);
    background: linear-gradient(180deg, var(--color-five), var(--color-four));
    box-shadow: inset 0 10px 10px 0 var(--color-three),
      inset 0 -10px 10px 0 var(--color-four);
  }

  .loader .box {
    width: 100px;
    height: 100px;
    background: linear-gradient(
      180deg,
      var(--color-one) 30%,
      var(--color-two) 70%
    );
    mask: url(#clipping);
    -webkit-mask: url(#clipping);
  }

  .loader svg {
    position: absolute;
  }

  .loader svg #clipping {
    filter: contrast(15);
    animation: roundness calc(var(--time-animation) / 2) linear infinite;
  }

  .loader svg #clipping polygon {
    filter: blur(7px);
  }

  .loader svg #clipping polygon:nth-child(1) {
    transform-origin: 75% 25%;
    transform: rotate(90deg);
  }

  .loader svg #clipping polygon:nth-child(2) {
    transform-origin: 50% 50%;
    animation: rotation var(--time-animation) linear infinite reverse;
  }

  .loader svg #clipping polygon:nth-child(3) {
    transform-origin: 50% 60%;
    animation: rotation var(--time-animation) linear infinite;
    animation-delay: calc(var(--time-animation) / -3);
  }

  .loader svg #clipping polygon:nth-child(4) {
    transform-origin: 40% 40%;
    animation: rotation var(--time-animation) linear infinite reverse;
  }

  .loader svg #clipping polygon:nth-child(5) {
    transform-origin: 40% 40%;
    animation: rotation var(--time-animation) linear infinite reverse;
    animation-delay: calc(var(--time-animation) / -2);
  }

  .loader svg #clipping polygon:nth-child(6) {
    transform-origin: 60% 40%;
    animation: rotation var(--time-animation) linear infinite;
  }

  .loader svg #clipping polygon:nth-child(7) {
    transform-origin: 60% 40%;
    animation: rotation var(--time-animation) linear infinite;
    animation-delay: calc(var(--time-animation) / -1.5);
  }

  @keyframes rotation {
    0% {
      transform: rotate(0deg);
    }
    100% {
      transform: rotate(360deg);
    }
  }

  @keyframes roundness {
    0% {
      filter: contrast(15);
    }
    20% {
      filter: contrast(3);
    }
    40% {
      filter: contrast(3);
    }
    60% {
      filter: contrast(15);
    }
    100% {
      filter: contrast(15);
    }
  }

  @keyframes colorize {
    0% {
      filter: hue-rotate(0deg);
    }
    20% {
      filter: hue-rotate(-30deg);
    }
    40% {
      filter: hue-rotate(-60deg);
    }
    60% {
      filter: hue-rotate(-90deg);
    }
    80% {
      filter: hue-rotate(-45deg);
    }
    100% {
      filter: hue-rotate(0deg);
    }
  }
`;

export default SparkIgniteAnimation;
