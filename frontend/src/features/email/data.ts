import { createResource, type Resource } from "solid-js";
import type {
  EmailAccount,
  EmailFolder,
  EmailMessage,
  ReplySuggestion,
} from "./model";
import {
  mockAccounts,
  mockFolders,
  mockMessages,
  mockReplySuggestions,
} from "./mocks";

async function fetchAccounts(): Promise<EmailAccount[]> {
  return mockAccounts;
}

async function fetchFolders(): Promise<EmailFolder[]> {
  return mockFolders;
}

async function fetchMessages(): Promise<EmailMessage[]> {
  return mockMessages;
}

async function fetchReplySuggestions(): Promise<ReplySuggestion[]> {
  return mockReplySuggestions;
}

export function useEmailAccounts(): Resource<EmailAccount[]> {
  const [data] = createResource(fetchAccounts);
  return data;
}

export function useEmailFolders(): Resource<EmailFolder[]> {
  const [data] = createResource(fetchFolders);
  return data;
}

export function useEmailMessages(): Resource<EmailMessage[]> {
  const [data] = createResource(fetchMessages);
  return data;
}

export function useReplySuggestions(): Resource<ReplySuggestion[]> {
  const [data] = createResource(fetchReplySuggestions);
  return data;
}
