import React, { createContext, useContext, useState, useCallback, useEffect, ReactNode } from "react";
import { useAcademicYears } from "../hooks/useAcademicYears";
import type { AcademicYear } from "../services/academicYearService";
import { getSelectedAcademicYearId, setSelectedAcademicYearId as persistSelectedAcademicYearId } from "@/common/utils/storage";

type AcademicYearContextType = {
  /** Currently selected academic year ID for filtering across the app. Empty = show all. */
  selectedAcademicYearId: string;
  setSelectedAcademicYearId: (id: string) => void;
  /** All academic years for the dropdown */
  academicYears: AcademicYear[];
  isLoading: boolean;
};

const AcademicYearContext = createContext<AcademicYearContextType | undefined>(undefined);

export function AcademicYearProvider({ children }: { children: ReactNode }) {
  const [selectedAcademicYearId, setSelectedAcademicYearId] = useState<string>("");
  const [hydrationDone, setHydrationDone] = useState(false);
  const { data: academicYears = [], isLoading } = useAcademicYears(false);

  // Hydrate from persisted storage on mount
  useEffect(() => {
    getSelectedAcademicYearId().then((id) => {
      setSelectedAcademicYearId(id ?? "");
      setHydrationDone(true);
    });
  }, []);

  // If persisted ID no longer exists in academic years (e.g. deleted), clear it
  useEffect(() => {
    if (hydrationDone && !isLoading && academicYears.length > 0 && selectedAcademicYearId) {
      const exists = academicYears.some((ay) => ay.id === selectedAcademicYearId);
      if (!exists) {
        setSelectedAcademicYearId("");
        persistSelectedAcademicYearId("");
      }
    }
  }, [hydrationDone, isLoading, academicYears, selectedAcademicYearId]);

  // Persist when selection changes
  const setSelected = useCallback((id: string) => {
    setSelectedAcademicYearId(id);
    persistSelectedAcademicYearId(id);
  }, []);

  return (
    <AcademicYearContext.Provider
      value={{
        selectedAcademicYearId,
        setSelectedAcademicYearId: setSelected,
        academicYears,
        isLoading,
      }}
    >
      {children}
    </AcademicYearContext.Provider>
  );
}

export function useAcademicYearContext() {
  const ctx = useContext(AcademicYearContext);
  if (!ctx) {
    throw new Error("useAcademicYearContext must be used within AcademicYearProvider");
  }
  return ctx;
}
