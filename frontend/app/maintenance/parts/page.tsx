"use client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { MasterPage } from "@/components/supply/MasterPage";
export default function Page() {
  const [categories, setCategories] = useState(false);
  const { t } = useTranslation("modules");
  return (
    <>
      <div className="actions spaced">
        <button
          className="secondaryButton"
          onClick={() => setCategories(!categories)}
        >
          {t(`supply.${categories ? "parts" : "part-categories"}`)}
        </button>
      </div>
      <MasterPage
        key={String(categories)}
        kind={categories ? "part-categories" : "parts"}
      />
    </>
  );
}
