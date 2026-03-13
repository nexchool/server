import { getApiUrl } from "@/common/constants/api";
import {
  getAccessToken,
  getRefreshToken,
  getTenantId,
  setAccessToken,
} from "@/common/utils/storage";

export class ApiException extends Error {
  status?: number;
  data?: any;

  constructor(message: string, status?: number, data?: any) {
    super(message);
    this.name = "ApiException";
    this.status = status;
    this.data = data;
  }
}

const apiRequest = async (
  endpoint: string,
  options: RequestInit = {},
  skipJsonContentType = false,
): Promise<Response> => {
  const url = getApiUrl(endpoint);
  const [accessToken, refreshToken, tenantId] = await Promise.all([
    getAccessToken(),
    getRefreshToken(),
    getTenantId(),
  ]);

  const headers: Record<string, string> = skipJsonContentType
    ? { ...(options.headers as Record<string, string>) }
    : {
        "Content-Type": "application/json",
        ...(options.headers as Record<string, string>),
      };

  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  }
  if (refreshToken) {
    headers["X-Refresh-Token"] = refreshToken;
  }
  if (tenantId) {
    headers["X-Tenant-ID"] = tenantId;
  }

  try {
    const response = await fetch(url, { ...options, headers });

    // Handle transparent token refresh
    // Backend sends 'X-New-Access-Token' header if access token was expired but refresh was valid
    const newAccessToken = response.headers.get("X-New-Access-Token");
    if (newAccessToken) {
      console.log("Token refreshed transparently");
      await setAccessToken(newAccessToken);
    }

    return response;
  } catch (error: any) {
    throw new ApiException(
      `Cannot connect to server. Please check your network connection.`,
      0,
      { originalError: error.message, url },
    );
  }
};

const handleResponse = async <T>(response: Response): Promise<T> => {
  const isJson = response.headers
    .get("content-type")
    ?.includes("application/json");

  let data: any;
  try {
    data = isJson ? await response.json() : await response.text();
  } catch {
    throw new ApiException("Failed to parse response", response.status);
  }

  // Handle standardized backend response structure: { success, data, message, error }
  // Backend returns success=true for successful operations
  if (data && typeof data === 'object' && 'success' in data) {
    if (data.success) {
      // If data.data exists, use it, otherwise default to empty object
      // We merge the top-level 'message' into the result so consumers can use it (e.g. MessageResponse)
      const resultData = (data.data && typeof data.data === 'object') ? data.data : (data.data !== undefined ? { value: data.data } : {});
      
      if (data.message && typeof resultData === 'object' && !Array.isArray(resultData)) {
        resultData.message = data.message;
      }
      
      return resultData as T;
    } else {
      // Backend returned logic error (success=false)
      throw new ApiException(
        data.message || data.error || 'An error occurred',
        response.status,
        data
      );
    }
  }

  // Fallback for non-standard responses (e.g. from 3rd party or legacy endpoints)
  if (!response.ok) {
    throw new ApiException(
      data?.error || data?.message || "An error occurred",
      response.status,
      data,
    );
  }

  return data as T;
};

export const apiGet = async <T>(endpoint: string): Promise<T> => {
  const response = await apiRequest(endpoint, { method: "GET" });
  return handleResponse<T>(response);
};

export const apiPost = async <T>(endpoint: string, body?: any): Promise<T> => {
  const response = await apiRequest(endpoint, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  });
  return handleResponse<T>(response);
};

/** POST with FormData (multipart). Omits Content-Type so fetch sets boundary. */
export const apiPostForm = async <T>(endpoint: string, formData: FormData): Promise<T> => {
  const response = await apiRequest(
    endpoint,
    { method: "POST", body: formData },
    true,
  );
  return handleResponse<T>(response);
};

export const apiPut = async <T>(endpoint: string, body?: any): Promise<T> => {
  const response = await apiRequest(endpoint, {
    method: "PUT",
    body: body ? JSON.stringify(body) : undefined,
  });
  return handleResponse<T>(response);
};

export const apiPatch = async <T>(endpoint: string, body?: any): Promise<T> => {
  const response = await apiRequest(endpoint, {
    method: "PATCH",
    body: body ? JSON.stringify(body) : undefined,
  });
  return handleResponse<T>(response);
};

export const apiDelete = async <T>(endpoint: string, body?: Record<string, unknown>): Promise<T> => {
  const response = await apiRequest(endpoint, {
    method: "DELETE",
    body: body ? JSON.stringify(body) : undefined,
  });
  return handleResponse<T>(response);
};
