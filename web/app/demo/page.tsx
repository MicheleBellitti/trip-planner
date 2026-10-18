import type { Metadata } from "next";

import { DemoPlanScreen } from "@/components/demo/demo-plan-screen";

export const metadata: Metadata = {
  title: "Corsa dimostrativa",
  description:
    "Una corsa registrata di cinque agenti AI che pianificano un viaggio a Lisbona, dalla richiesta al piano con le date entro cui prenotare.",
};

/**
 * "/demo": the self-playing demo run (brand spec, "Demo"), public and prerendered. It replays a
 * recorded run in the browser and never calls the backend.
 */
export default function DemoPage() {
  return <DemoPlanScreen />;
}
