import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import SharedMemory from "./SharedMemory";
import "./styles.css";
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {window.location.pathname.startsWith("/s/") ? <SharedMemory /> : <App />}
  </React.StrictMode>,
);
