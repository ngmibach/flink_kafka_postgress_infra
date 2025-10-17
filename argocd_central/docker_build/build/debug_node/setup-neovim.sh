#!/bin/bash

# Setup config dir
echo "[INFO] Setting up Neovim config..."
mkdir -p ~/.config/nvim/lua/custom
mkdir -p ~/.local/share/nvim/site/pack/lazy/start

# Plugin manager: lazy.nvim
if [ ! -d ~/.local/share/nvim/site/pack/lazy/start/lazy.nvim ]; then
  git clone https://github.com/folke/lazy.nvim ~/.local/share/nvim/site/pack/lazy/start/lazy.nvim
fi

cat > /usr/local/bin/kubectl_df << 'EOF'
#!/bin/bash
NS="${1:-kube-system}"    # default namespace to kube-system
LBL="${2:-app=node-debug}" # default label selector to app=node-debug

printf "%-30s %-15s %-10s %-10s %-10s %-20s\n" "NODE" "FILESYSTEM" "USED" "AVAIL" "USE%" "MOUNT"

kubectl get pods -n "$NS" -l "$LBL" -o custom-columns=P:.metadata.name,N:.spec.nodeName --no-headers | while read -r POD NODE; do
  kubectl exec -n "$NS" "$POD" -- chroot /hostdir sh -c "df -h | grep -vE '^Filesystem|tmpfs|overlay|shm'" | while read -r LINE; do
    printf "%-30s %-15s %-10s %-10s %-10s %-20s\n" \
      "$NODE" \
      $(awk '{print $1, $3, $4, $5, $6}' <<< "$LINE")
  done
done
EOF

chmod +x /usr/local/bin/kubectl_df

# Create init.lua
cat > ~/.config/nvim/init.lua << 'EOF'
-- Prepend Lazy to runtime path
vim.opt.runtimepath:prepend(vim.fn.expand("~/.local/share/nvim/site/pack/lazy/start/lazy.nvim"))

require("lazy").setup({

  -- File Explorer
  {
    "nvim-tree/nvim-tree.lua",
    dependencies = {},
    config = function()
      require("nvim-tree").setup({
        hijack_netrw = true,
        respect_buf_cwd = true,
        update_cwd = true,
        view = { width = 30 },
        actions = {
          open_file = {
            quit_on_open = false,
          },
        },
        renderer = {
          icons = {
            web_devicons = {
              file = { enable = false },
              folder = { enable = false },
            },
            glyphs = {
              default = "-",
              symlink = ">",
              folder = {
                arrow_closed = "+",
                arrow_open = "-",
                default = "[+]",
                open = "[-]",
                empty = "[ ]",
                empty_open = "[ ]",
                symlink = ">",
                symlink_open = ">>",
              },
              git = {
                unstaged = "!",
                staged = "+",
                unmerged = "%",
                renamed = ">",
                untracked = "?",
                deleted = "x",
                ignored = ".",
              },
            },
          },
        }
      })

      -- Auto open NvimTree on startup if no file passed
      vim.api.nvim_create_autocmd({ "VimEnter" }, {
        callback = function()
          if vim.fn.argc() == 0 then
            require("nvim-tree.api").tree.open()
          end
        end
      })
    end
  },

  -- Syntax Highlighting
  {
    "nvim-treesitter/nvim-treesitter",
    build = ":TSUpdate",
    event = "BufReadPost",
    config = function()
      require("nvim-treesitter.configs").setup {
        highlight = { enable = true },
        indent = { enable = true }
      }
    end
  },

  -- Completion
  {
    "hrsh7th/nvim-cmp",
    dependencies = {
      "hrsh7th/cmp-nvim-lsp",
      "L3MON4D3/LuaSnip"
    },
    event = "InsertEnter",
    config = function()
      local cmp = require("cmp")
      cmp.setup({
        mapping = cmp.mapping.preset.insert({
          ['<CR>'] = cmp.mapping.confirm({ select = true }),
        }),
        sources = cmp.config.sources({
          { name = 'nvim_lsp' },
        })
      })
    end
  },

  -- Split Maximizer
  {
    "szw/vim-maximizer",
    keys = {
      { "<leader>z", ":MaximizerToggle<CR>", desc = "Toggle maximize split" }
    }
  },

  -- Fuzzy Finder
  {
    "nvim-telescope/telescope.nvim",
    dependencies = { "nvim-lua/plenary.nvim" },
    cmd = "Telescope",
    config = function()
      require("telescope").setup()
    end
  }
})

-- Keymaps
local map = vim.keymap.set
local builtin = require("telescope.builtin")

map("n", "<leader>e", ":NvimTreeToggle<CR>", { noremap = true, silent = true, desc = "Toggle file explorer" })
map("n", "<leader>t", function()
  local api = require("nvim-tree.api")
  local uv = vim.loop
  local node = api.tree.get_node_under_cursor()
  local dir = nil

  if node then
    local path = node.absolute_path or node.name
    local stat = uv.fs_stat(path)
    dir = (stat and stat.type == "directory") and path or vim.fn.fnamemodify(path, ":h")
  else
    print("No node selected.")
    return
  end

  vim.cmd("wincmd l")
  vim.cmd("split")
  vim.cmd("wincmd j")
  vim.cmd("enew")
  if dir then uv.chdir(dir) end
  vim.fn.termopen("/bin/bash")
  vim.cmd("startinsert")
end, { noremap = true, silent = true, desc = "Open terminal at selected NvimTree path" })

map("n", "<leader>ff", builtin.find_files, { desc = "Find Files" })
map("n", "<leader>fg", builtin.live_grep,  { desc = "Live Grep" })
map("n", "<leader>fb", builtin.buffers,    { desc = "Buffers" })
map("n", "<leader>fh", builtin.help_tags,  { desc = "Help Tags" })
EOF

# Install plugins
echo "[✅] Installing plugins..."
nvim --headless +"Lazy! sync" +"autocmd User LazySyncComplete quitall" +qa
echo "[✅] Plugins installed. Launch with: nvim"
