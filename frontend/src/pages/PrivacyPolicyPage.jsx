import React from 'react';
import { Link } from 'react-router-dom';

const Section = ({ title, children }) => (
  <section className="border-b border-slate-200 py-8 last:border-b-0">
    <h2 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h2>
    <div className="mt-3 space-y-3 text-sm leading-7 text-slate-600">{children}</div>
  </section>
);

const BulletList = ({ children }) => (
  <ul className="list-disc space-y-2 pl-5 marker:text-green-600">{children}</ul>
);

export default function PrivacyPolicyPage() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 antialiased">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-4xl px-6 py-12 sm:px-8">
          <Link to="/" className="text-sm font-medium text-green-700 hover:text-green-800">
            ← Back to LexAI
          </Link>
          <p className="mt-8 text-sm font-medium text-green-700">Your information and documents</p>
          <h1 className="mt-2 text-4xl font-semibold tracking-tight text-slate-900">
            Privacy Policy
          </h1>
          <p className="mt-3 text-sm text-slate-500">Last updated: November 12, 2026</p>
          <p className="mt-5 max-w-3xl text-sm leading-7 text-slate-600">
            This policy describes how the current LexAI application handles information. The
            service may be configured or hosted by different operators, so the actual storage
            location and providers depend on the deployment you use.
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-8 sm:px-8 sm:py-12">
        <div className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
          <strong>Before using the service:</strong> legal documents and case details can be
          sensitive. Only upload information you are authorized to share, and review the
          deployment operator’s provider and storage settings before uploading confidential
          material. This page describes the application’s current behavior; the operator should
          review it for the laws and requirements that apply to their deployment.
        </div>

        <article className="rounded-2xl border border-slate-200 bg-white px-6 sm:px-9">
          <Section title="Information the application handles">
            <p>Depending on how you use the service, it may process and store:</p>
            <BulletList>
              <li>
                <strong>Account information:</strong> name, email address, role, and any profile
                details you choose to provide. Passwords are stored as password hashes rather
                than plain text.
              </li>
              <li>
                <strong>Case and document information:</strong> uploaded files, extracted text,
                analysis reports, corrections, chat messages, case details, and generated
                documents.
              </li>
              <li>
                <strong>Security and activity information:</strong> sign-in/session records and
                related activity details, which may include IP address and browser user-agent
                information.
              </li>
              <li>
                <strong>Browser storage:</strong> the web app stores authentication tokens,
                account and active-case information, and your theme preference in browser
                local storage.
              </li>
            </BulletList>
          </Section>

          <Section title="How information is used">
            <p>Information is processed to provide the application, including to:</p>
            <BulletList>
              <li>create and secure accounts, maintain sessions, and send verification or password-reset messages;</li>
              <li>extract text from uploaded documents and prepare analysis reports;</li>
              <li>answer legal research questions using the case context and retrieved authorities;</li>
              <li>collect information needed to prepare requested document drafts; and</li>
              <li>save case history and support troubleshooting, security, and service operation.</li>
            </BulletList>
          </Section>

          <Section title="AI and service providers">
            <p>
              To provide its features, a deployment may send relevant information to services
              configured by its operator:
            </p>
            <BulletList>
              <li>
                <strong>LlamaCloud:</strong> uploaded documents are sent for text extraction and
                document parsing.
              </li>
              <li>
                <strong>Groq:</strong> extracted document text may be used for document analysis;
                document-generation requests and relevant case context may be sent to prepare
                drafts.
              </li>
              <li>
                <strong>Ollama:</strong> legal chat requests, relevant conversation/case context,
                and retrieved legal passages are sent to the configured Ollama endpoint. It is
                local only when the deployment is configured to use a local Ollama service.
              </li>
              <li>
                <strong>Email provider:</strong> account email addresses and verification or
                password-reset links may be sent through the configured Resend or SMTP service.
              </li>
              <li>
                <strong>Database provider:</strong> account, case, document, activity, and
                session records may be stored in the configured MongoDB database.
              </li>
            </BulletList>
            <p>
              These providers process information under their own terms and privacy practices.
              The deployment operator chooses the provider configuration; check with that
              operator for details about the services and locations used by your deployment.
            </p>
          </Section>

          <Section title="Storage and retention">
            <p>
              Storage depends on deployment settings. When MongoDB persistence is enabled,
              records are stored in the configured database. When it is disabled, runtime case
              data is held in server memory and may be lost when the server restarts. Uploaded
              originals and generated files may also be stored on the server.
            </p>
            <p>
              The application does not define one retention period for every deployment.
              Archiving a document may leave its extracted text and report in place; ask the
              deployment operator how to request deletion and whether backups or provider-held
              copies are also removed.
            </p>
            <p>
              Clearing browser local storage removes the locally saved browser data but does
              not delete information already stored by the server or its providers.
            </p>
          </Section>

          <Section title="Security">
            <p>
              The application uses measures such as password hashing and account-scoped data
              access. No website, storage system, or network transmission can be guaranteed
              completely secure. Protect your account credentials and avoid entering passwords,
              access keys, or unrelated highly sensitive information into chats or documents.
            </p>
          </Section>

          <Section title="Your choices and privacy questions">
            <p>
              You can limit the information you provide and should avoid uploading documents
              unless you have permission to do so. For questions, access or deletion requests,
              or details about this deployment’s storage and AI providers, contact the
              administrator responsible for the LexAI service you use.
            </p>
          </Section>

          <Section title="Updates to this policy">
            <p>
              This policy may be updated when the application or its configuration changes.
              The “Last updated” date above indicates the latest revision shown on this page.
            </p>
          </Section>
        </article>
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3 px-6 py-6 text-sm text-slate-500 sm:px-8">
          <span>LexAI · Pakistan Legal Intelligence</span>
          <Link to="/" className="font-medium text-green-700 hover:text-green-800">
            Home
          </Link>
        </div>
      </footer>
    </div>
  );
}
