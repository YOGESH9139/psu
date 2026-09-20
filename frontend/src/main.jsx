import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/sora";
import "@fontsource-variable/plus-jakarta-sans";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
import App from "./App";
import "./styles.css";
import "./panels.css";
import "./extra.css";
import "./brand.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);
