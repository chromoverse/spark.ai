import * as React from "react";
import { useNavigate } from "react-router-dom";

type As = "button" | "a" | "div";

interface PressableProps extends React.HTMLAttributes<HTMLElement> {
  as?: As;
  to?: string;
  href?: string;
  disabled?: boolean;
}

export const Pressable = React.forwardRef<HTMLElement, PressableProps>(
  (
    { as = "button", to, href, disabled, className = "", children, ...props },
    ref
  ) => {
    const navigate = useNavigate();
    const Comp = as as any;

    const handleClick = (e: React.MouseEvent<HTMLElement>) => {
      if (disabled) return;

      const el = e.currentTarget as HTMLElement;
      el.classList.remove("pressable");
      void el.offsetHeight;
      el.classList.add("pressable");

      if (to) setTimeout(() => navigate(to), 160);
      if (href) window.open(href, "_self");

      props.onClick?.(e);
    };

    return (
      <Comp
        ref={ref}
        onClick={handleClick}
        aria-disabled={disabled}
        role={as !== "button" ? "button" : undefined}
        tabIndex={disabled ? -1 : 0}
        className={`select-none webkit-drag-nodrag inline-flex items-center justify-center gap-2 outline-none 
        ${disabled ? "opacity-50 pointer-events-none" : "cursor-pointer"}
        ${className}`}
        {...props}
      >
        {children}
      </Comp>
    );
  }
);
