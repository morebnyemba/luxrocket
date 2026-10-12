"use client";
import { useEffect, useState } from "react";
import { GameController } from "@/lib/controller";
import { GameView } from "./GameView";

export function GameRoot() {
  const [controller] = useState(() => new GameController());

  useEffect(() => {
    void controller.start();
    return () => controller.stop();
  }, [controller]);

  return <GameView controller={controller} />;
}
