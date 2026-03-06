import { useQuery } from "@tanstack/react-query";
import { academicYearService } from "../services/academicYearService";

const KEYS = ["academics", "academicYears"] as const;

export function useAcademicYears(activeOnly = false) {
  return useQuery({
    queryKey: [...KEYS, activeOnly],
    queryFn: () => academicYearService.getAcademicYears(activeOnly),
  });
}
