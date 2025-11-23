# Vibe Coding - Jamf Tools

**Weekend Projects for Real-World IT Automation**

> **Disclaimer**: This repository contains tools created with AI assistance (Claude Code by Anthropic) as weekend projects to solve real organizational needs. I do not warrant the contents or guarantee functionality in all environments, especially large-scale deployments. Use at your own risk and test thoroughly in your environment before production use.

---

## About This Repository

This repository houses IT automation tools I've built to solve real problems in my organization, created collaboratively with [Claude Code](https://claude.ai/code) during weekend coding sessions. The projects here represent practical solutions to common IT challenges, particularly around Apple device management with Jamf Pro.

### Philosophy

**"Vibe Coding"** - The intersection of human need and AI capability:
- 🎯 **Real problems** - Not toy projects, actual challenges
- 🤖 **Directed AI Creation** - Built collaboratively with Claude Code
- ⚡ **Rapid development** - Weekend projects to solve specific issues and test real-world applicability
- 🔬 **Experimental** - May not work in all environments, especially at scale
- 📚 **Learning** - Each project is a learning experience

---

## Projects

### 📁 [jamf-health-tool](./jamf-health-tool/)

**Complete Change Request (CR) automation for Jamf Pro**

A comprehensive CLI tool for validating, remediating, and analyzing Change Requests in Jamf-managed environments. Built over a weekend to automate what previously took hours of manual validation.
Best for organizations that must deploy policies and configuration profiles during a specific time frame, and more importantly, report on the success rate of that deployment within the time frame. 
Change Request can go by other names like Deployment Window, Change Management Window, and more. 
All testing has been done against a dedicated test Jamf Cloud environment.

**What it does:**
- ✅ Validates patch compliance (macOS and applications)
- ✅ Analyzes device availability during CR windows
- ✅ Tracks policy execution and failures
- ✅ Automatically remediates failures with intelligent retry
- ✅ Compares CR performance over time
- ✅ Generates reports (JSON, Excel, PDF, HTML)

**Key metrics:**
- 16 production commands
- 98% API call reduction
- 40x faster CR validation (10min → 20sec)
- 6,000+ lines of documentation

**Status:** ✅ Production-ready, actively used

[**View Full Documentation →**](./jamf-health-tool/README.md)

---

## What is CR (Change Request)?

**CR = Change Request** - A formal process for managing changes to IT systems.

### The Change Management Workflow

In IT organizations, changes to systems follow a structured process:

```
┌─────────────────────────────────────────────────────────────┐
│                    CHANGE MANAGEMENT PROCESS                 │
└─────────────────────────────────────────────────────────────┘

1. PLANNING
   ├─ Define scope and objectives
   ├─ Identify affected systems
   └─ Schedule maintenance window

2. PRE-CR PREPARATION (Pre-Flight)
   ├─ Validate device readiness
   ├─ Check resource availability
   ├─ Prepare rollback plans
   └─ Stakeholder communication

3. CR EXECUTION (Change Window)
   ├─ Apply updates/changes
   ├─ Monitor progress
   ├─ Handle failures
   └─ Real-time remediation

4. VALIDATION (Quality Assurance)
   ├─ Verify successful deployment
   ├─ Check compliance targets
   ├─ Identify failures
   └─ Document exceptions

5. POST-CR ANALYSIS
   ├─ Generate compliance reports
   ├─ Trend analysis
   ├─ Lessons learned
   └─ Process improvements

6. CLOSURE
   ├─ Final documentation
   ├─ Stakeholder sign-off
   └─ Archive results
```

### CR in Different IT Contexts

**Patch Management:**
- Monthly OS updates (macOS 15.1, 14.7.1, etc.)
- Application updates (Safari, Chrome, Office)
- Security patch deployment
- Compliance validation

**Configuration Management:**
- Security baseline deployment
- Policy updates
- Profile installation
- Settings standardization

**Quality Assurance (QA):**
- Pre-production testing
- Staged rollouts
- Rollback readiness
- Success criteria validation

---

## How These Tools Fit the CR Workflow

### jamf-health-tool's Role:

**Pre-CR Preparation (Phase 2):**
```bash
# Check if devices are ready BEFORE CR starts
jamf-health-tool cr-readiness --scope-group-id 100

# Wake offline devices
jamf-health-tool wake-devices --computer-list scope.txt

# Ensure fresh inventory
jamf-health-tool update-inventory --computer-list scope.txt
```

**During CR (Phase 3):**
```bash
# Auto-remediate failures as they occur
jamf-health-tool auto-remediate \
  --policy-id 100 --policy-id 101 \
  --max-retries 3 --send-blank-push
```

**Validation (Phase 4):**
```bash
# Comprehensive CR validation
jamf-health-tool cr-summary \
  --cr-name "November 2024 Patching" \
  --cr-start "2024-11-18T00:00:00Z" \
  --cr-end "2024-11-22T23:59:59Z" \
  --target-os-version "15.1" \
  --success-threshold 0.95
```

**Post-CR Analysis (Phase 5):**
```bash
# Compare with previous CR
jamf-health-tool cr-compare \
  --current nov_cr.json \
  --previous oct_cr.json

# Identify chronic problem devices
jamf-health-tool problem-devices \
  --cr-summary sept_cr.json \
  --cr-summary oct_cr.json \
  --cr-summary nov_cr.json
```

---

## Built With Claude Code

All tools in this repository were created collaboratively with [Claude Code](https://claude.ai/code), Anthropic's AI coding assistant. Additionally, OpenAI's ChatGPT Codex was used in testing and idea generation.

### The Development Process

**Human contribution:**
- 🎯 Identified real organizational problems
- 📋 Defined requirements and use cases
- ✅ Tested functionality
- 📚 Validated documentation
- 🔍 QA and iteration

**AI contribution (Claude Code):**
- 💻 Wrote 95%+ of the code
- 📖 Generated comprehensive documentation
- 🧪 Created unit tests
- 🎨 Designed CLI interfaces
- 🚀 Optimized performance

### Why This Matters

**Traditional development timeline:**
- Weeks to months for a tool like jamf-health-tool
- Multiple iterations and rewrites
- Extensive debugging and optimization

**AI-assisted development timeline:**
- Weekend project (2-3 days)
- Immediate production quality
- Comprehensive documentation included
- Built-in best practices

This represents a **10-100x acceleration** in development time while maintaining or exceeding traditional quality standards.
This repository differs from others and has been purposely separated due to the amount of code that is AI-generated. While the ideas and the problems came from a real place, the original intention of utilizing AI was to provide a fast turn around time to see the applicability of the solution. This very README was partially generated with AI, with human editing afterwards.

---

## Important Notes

### ⚠️ Disclaimers

1. **No Warranty**: These tools are provided as-is, without any warranty of fitness for purpose or merchantability.

2. **Test First**: Always test thoroughly in a non-production environment before deploying to production.

3. **Scale Considerations**: Tools were developed and tested in mid-size environments (~1,000 devices). Performance in large-scale environments (10,000+ devices) may vary.

4. **Environment Specific**: Your Jamf Pro configuration, network topology, and organizational policies may affect functionality.

5. **API Changes**: Jamf Pro API changes may require updates to these tools.

6. **Support**: These are personal projects. While I'll do my best to help, I cannot guarantee support or timely updates.

### ✅ Best Practices

Before using any tool in this repository:

1. **Read the documentation** thoroughly
2. **Test in development** environment first  
3. **Understand the code** - review what it does
4. **Verify permissions** - ensure you have appropriate access
5. **Have a rollback plan** - know how to undo changes
6. **Monitor execution** - watch what happens during first runs
7. **Start small** - pilot with a small group before full deployment

### 🔐 Security Considerations

- **Read-only by default**: Most tools use read-only API access
- **OAuth recommended**: Use OAuth tokens instead of basic auth
- **Credential management**: Never commit credentials to version control
- **Environment variables**: Use environment variables for sensitive data
- **Audit logging**: Tools log all operations for audit trails
- **Dry-run modes**: Test commands have dry-run options

---

## Getting Started

### Prerequisites

- Python 3.8 or higher
- Jamf Pro instance with API access
- OAuth client credentials (recommended) or Bearer token
- Read permissions for Jamf Pro API

### Quick Start

1. **Choose a project** from the repository
2. **Read the project README** for specific setup instructions
3. **Install dependencies** (each project has its own requirements)
4. **Configure authentication** (typically via environment variables)
5. **Test with --help** to understand available commands
6. **Run in dry-run mode** first (if available)
7. **Start with small scope** before full deployment

### Example: jamf-health-tool

```bash
# Clone repository
git clone https://github.com/tonyyo11/vibe-coding-jamf.git
cd vibe-coding-jamf/jamf-health-tool

# Install
pip install -e ".[reports]"

# Configure
export JAMF_BASE_URL="https://yourserver.jamfcloud.com"
export JAMF_CLIENT_ID="your-client-id"
export JAMF_CLIENT_SECRET="your-client-secret"

# Test
jamf-health-tool --version
jamf-health-tool cr-readiness --help

# Use
jamf-health-tool patch-compliance --os-version "15.1"
```

---

## Contributing

While these are personal weekend projects, I welcome:
- 🐛 Bug reports (please include environment details)
- 💡 Feature suggestions (especially for real-world use cases)
- 📚 Documentation improvements
- 🔧 Pull requests (with detailed descriptions)

**Note**: Response times may vary as these are maintained in my spare time.

---

## License

[MIT License](LICENSE) - Use freely, but without warranty.

---

## Acknowledgments

### Claude Code by Anthropic

This repository wouldn't exist without [Claude Code](https://claude.ai/code). The AI assistant:
- Wrote the majority of the code
- Generated comprehensive documentation
- Created unit tests
- Provided optimization insights
- Enabled rapid iteration

**This represents the future of software development** - human creativity and problem identification combined with AI implementation speed and consistency.

### Inspiration

These tools were born from real frustration:
- ⏱️ Hours spent manually validating CRs
- 📊 Inconsistent reporting across maintenance windows
- ❌ Human error in compliance calculations
- 🔄 Repetitive tasks that should be automated

If you face similar challenges, I hope these tools help you too.

---

## Final Thoughts

These tools represent what's possible when human domain expertise meets AI coding capability. They're not perfect, but they're practical, functional, and solve real problems.

**If you use these tools in your organization:**
- ⭐ Star this repository
- 📝 Share your experience in Discussions
- 🐛 Report bugs to help improve them
- 🙏 Pay it forward - share your own solutions

**Remember**: Always test thoroughly, understand what the code does, and use at your own risk.

---

**Created with ❤️, weekends, and Claude Code**

**Version**: 1.0  
**Last Updated**: November 2025
**Status**: Active Development
