import { apiDelete, apiGet, apiPostForm } from '@/common/services/api';
import type { StudentDocument, UploadDocumentInput } from '../types';

export async function getStudentDocuments(
  studentId: string,
): Promise<StudentDocument[]> {
  const data = await apiGet<StudentDocument[]>(
    `/api/students/${studentId}/documents`,
  );
  return Array.isArray(data) ? data : [];
}

export async function uploadStudentDocument(
  studentId: string,
  input: UploadDocumentInput,
): Promise<StudentDocument> {
  const formData = new FormData();
  formData.append('document_type', input.documentType);
  // React Native FormData expects { uri, name, type } for file uploads
  const fileUri = input.file.uri.startsWith('file://') || input.file.uri.startsWith('content://')
    ? input.file.uri
    : `file://${input.file.uri}`;
  formData.append('file', {
    uri: fileUri,
    name: input.file.name,
    type: input.file.mimeType || 'application/octet-stream',
  } as unknown as Blob);
  return apiPostForm<StudentDocument>(
    `/api/students/${studentId}/documents`,
    formData,
  );
}

export async function deleteStudentDocument(
  studentId: string,
  documentId: string,
): Promise<void> {
  await apiDelete<void>(
    `/api/students/${studentId}/documents/${documentId}`,
  );
}
