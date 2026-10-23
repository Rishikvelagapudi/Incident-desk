import { useEffect, useState } from "react";
import { api } from "./api";
import Dashboard from "./Dashboard.jsx";
import Workbench from "./Workbench.jsx";
import Settings from "./Settings.jsx";
import "./styles.css";

export default function App() {
  const [user, setUser] = useState("Operator");
  const [path, setPath] = useState(location.pathname + location.search);

  useEffect(() => {
    api("/api/me").then((r) => r.user && setUser(r.user)).catch(() => {});
    const onPop = () => setPath(location.pathname + location.search);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = (p) => {
    history.pushState({}, "", p);
    setPath(p);
    window.scrollTo(0, 0);
  };

  const m = path.match(/^\/incidents\/([\w-]+)/);
  if (m) {
    return <Workbench id={m[1]} user={user} navigate={navigate} />;
  }
  if (path.startsWith("/settings")) {
    return <Settings user={user} navigate={navigate} path={path} />;
  }
  return <Dashboard user={user} navigate={navigate} />;
}
