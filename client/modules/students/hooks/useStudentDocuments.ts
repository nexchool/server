import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getStudentDocuments,
  uploadStudentDocument,
  deleteStudentDocument,
} from "../services/studentDocumentService";
import type { UploadDocumentInput } from "../types";

export const QUERY_KEY_STUDENT_DOCUMENTS = "student-documents";

export type { UploadDocumentInput };

export function useStudentDocuments(studentId: string | undefined) {
  return useQuery({
    queryKey: [QUERY_KEY_STUDENT_DOCUMENTS, studentId],
    queryFn: () => getStudentDocuments(studentId!),
    enabled: !!studentId,
  });
}

export function useUploadStudentDocument(studentId: string | undefined) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: UploadDocumentInput) =>
      uploadStudentDocument(studentId!, input),
    onSuccess: () => {
      if (studentId) {
        queryClient.invalidateQueries({
          queryKey: [QUERY_KEY_STUDENT_DOCUMENTS, studentId],
        });
      }
    },
  });
}

export function useDeleteStudentDocument(studentId: string | undefined) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (documentId: string) =>
      deleteStudentDocument(studentId!, documentId),
    onSuccess: () => {
      if (studentId) {
        queryClient.invalidateQueries({
          queryKey: [QUERY_KEY_STUDENT_DOCUMENTS, studentId],
        });
      }
    },
  });
}
