import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { routes } from "./App";
import { useSession } from "./auth/session";

vi.mock("./auth/session", () => ({ useSession: vi.fn() }));
const actions = { login: vi.fn(), logout: vi.fn(), reloadUser: vi.fn() };

it("renders the public introduction without inventing financial data", async () => {
  render(
    <RouterProvider
      router={createMemoryRouter(routes, { initialEntries: ["/"] })}
    />,
  );
  expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
    "Understand today.",
  );
  expect(screen.getByText(/No example figures/)).toBeInTheDocument();
});

it("redirects anonymous users away from private routes", async () => {
  vi.mocked(useSession).mockReturnValue({
    status: "anonymous",
    user: null,
    ...actions,
  });
  render(
    <RouterProvider
      router={createMemoryRouter(routes, { initialEntries: ["/app/overview"] })}
    />,
  );
  expect(
    await screen.findByRole("heading", { name: "Sign in" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
});

it("does not silently label API failure as signed out", () => {
  vi.mocked(useSession).mockReturnValue({
    status: "error",
    user: null,
    ...actions,
  });
  render(
    <RouterProvider
      router={createMemoryRouter(routes, { initialEntries: ["/app/overview"] })}
    />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("API is unavailable");
});

it("requires verified identity", async () => {
  vi.mocked(useSession).mockReturnValue({
    status: "authenticated",
    ...actions,
    user: {
      id: "u",
      display_name: null,
      email: "synthetic@example.com",
      email_verified: false,
      timezone: "UTC",
      default_currency: "INR",
    },
  });
  render(
    <RouterProvider
      router={createMemoryRouter(routes, { initialEntries: ["/app/overview"] })}
    />,
  );
  expect(
    await screen.findByRole("heading", { name: "Verify your email" }),
  ).toBeInTheDocument();
});

it("provides navigation and a content landmark to verified users", () => {
  vi.mocked(useSession).mockReturnValue({
    status: "authenticated",
    ...actions,
    user: {
      id: "u",
      display_name: "Synthetic",
      email: "synthetic@example.com",
      email_verified: true,
      timezone: "UTC",
      default_currency: "INR",
    },
  });
  render(
    <RouterProvider
      router={createMemoryRouter(routes, {
        initialEntries: ["/app/assistant"],
      })}
    />,
  );
  expect(
    screen.getByRole("navigation", { name: "Main navigation" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("main")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /^Assistant$/ }),
  ).toBeInTheDocument();
});
