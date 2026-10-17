defmodule LuxRtWeb.ChannelCase do
  @moduledoc "Test case for channels."
  use ExUnit.CaseTemplate

  using do
    quote do
      import Phoenix.ChannelTest
      @endpoint LuxRtWeb.Endpoint
    end
  end

  setup tags do
    LuxRt.DataCase.setup_sandbox(tags)
    :ok
  end
end
