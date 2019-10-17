/// \file ROOT/RBrowser.cxx
/// \ingroup WebGui ROOT7
/// \author Bertrand Bellenot <bertrand.bellenot@cern.ch>
/// \date 2019-02-28
/// \warning This is part of the ROOT 7 prototype! It will change without notice. It might trigger earthquakes. Feedback
/// is welcome!

/*************************************************************************
 * Copyright (C) 1995-2019, Rene Brun and Fons Rademakers.               *
 * All rights reserved.                                                  *
 *                                                                       *
 * For the licensing terms see $ROOTSYS/LICENSE.                         *
 * For the list of contributors see $ROOTSYS/README/CREDITS.             *
 *************************************************************************/

#include <ROOT/RBrowser.hxx>

#include <ROOT/RBrowserItem.hxx>
#include <ROOT/RLogger.hxx>
#include <ROOT/RMakeUnique.hxx>
#include <ROOT/RObjectDrawable.hxx>
#include <ROOT/RFileBrowsable.hxx>


#include "TKey.h"
#include "TString.h"
#include "TSystem.h"
#include "TROOT.h"
#include "TWebCanvas.h"
#include "TCanvas.h"
#include "TFile.h"
#include "TH1.h"
#include "TBufferJSON.h"

#include <sstream>
#include <iostream>
#include <algorithm>
#include <memory>
#include <mutex>
#include <thread>
#include <fstream>

using namespace std::string_literals;

/** \class ROOT::Experimental::RBrowser
\ingroup rbrowser

web-based ROOT Browser prototype.
*/

//////////////////////////////////////////////////////////////////////////////////////////////
/// constructor

ROOT::Experimental::RBrowser::RBrowser(bool use_rcanvas)
{
   SetUseRCanvas(use_rcanvas);

   fWorkingDirectory = gSystem->WorkingDirectory();
   printf("Current dir %s\n", fWorkingDirectory.c_str());

   fBrowsable.SetTopItem(std::make_unique<RBrowsableSysFileElement>(fWorkingDirectory));

   fWebWindow = RWebWindow::Create();
   fWebWindow->SetDefaultPage("file:rootui5sys/browser/browser.html");

   // this is call-back, invoked when message received via websocket
   fWebWindow->SetCallBacks([this](unsigned connid) { fConnId = connid; SendInitMsg(connid); },
                            [this](unsigned connid, const std::string &arg) { WebWindowCallback(connid, arg); });
   fWebWindow->SetGeometry(1200, 700); // configure predefined window geometry
   fWebWindow->SetConnLimit(1); // the only connection is allowed
   fWebWindow->SetMaxQueueLength(30); // number of allowed entries in the window queue

   Show();

   // add first canvas by default

   if (GetUseRCanvas())
      AddRCanvas();
   else
      AddCanvas();
}

//////////////////////////////////////////////////////////////////////////////////////////////
/// destructor

ROOT::Experimental::RBrowser::~RBrowser()
{
   fCanvases.clear();
}


//////////////////////////////////////////////////////////////////////////////////////////////
/// Process browser request

std::string ROOT::Experimental::RBrowser::ProcessBrowserRequest(const std::string &msg)
{
   std::string res;

   std::unique_ptr<RBrowserRequest> request;

   if (msg.empty()) {
      request = std::make_unique<RBrowserRequest>();
      request->path = "/";
      request->first = 0;
      request->number = 100;
   } else {
      request = TBufferJSON::FromJSON<RBrowserRequest>(msg);
   }

   if (!request)
      return res;

   RBrowserReplyNew replynew;

   fBrowsable.ProcessRequest(*request.get(), replynew);

   res = "BREPL:";
   res.append(TBufferJSON::ToJSON(&replynew, TBufferJSON::kSkipTypeInfo + TBufferJSON::kNoSpaces).Data());

   return res;
}

/////////////////////////////////////////////////////////////////////////////////
/// Process file save command in the editor

bool ROOT::Experimental::RBrowser::ProcessSaveFile(const std::string &file_path)
{
   // Split the path (filename + text)
   std::vector<std::string> split;
   std::string buffer;
   std::istringstream path(file_path);
   if (std::getline(path, buffer, ':'))
      split.push_back(buffer);
   if (std::getline(path, buffer, '\0'))
      split.push_back(buffer);
   // TODO: can be done with RBrowsableElement as well
   std::ofstream ostrm(split[0]);
   ostrm << split[1];
   return true;
}

/////////////////////////////////////////////////////////////////////////////////
/// Process file save command in the editor

long ROOT::Experimental::RBrowser::ProcessRunCommand(const std::string &file_path)
{
   // Split the path (filename + text)
   std::vector<std::string> split;
   std::string buffer;
   std::istringstream path(file_path);
   if (std::getline(path, buffer, ':'))
      split.push_back(buffer);
   if (std::getline(path, buffer, '\0'))
      split.push_back(buffer);
   return gInterpreter->ExecuteMacro(split[0].c_str());
}

/////////////////////////////////////////////////////////////////////////////////
/// Process dbl click on browser item

std::string ROOT::Experimental::RBrowser::ProcessDblClick(const std::string &item_path, const std::string &drawingOptions)
{
   printf("DoubleClick %s\n", item_path.c_str());

   auto elem = fBrowsable.GetElement(item_path);
   if (!elem) return ""s;

   if (elem->HasTextContent())
      return "FREAD:"s + elem->GetTextContent();

   TObject *tobj = elem->GetObjectToDraw();

   if (!tobj)
      return ""s;

   auto canv = GetActiveCanvas();
   if (canv) {
      canv->GetListOfPrimitives()->Clear();

      canv->GetListOfPrimitives()->Add(tobj, drawingOptions.c_str());

      canv->ForceUpdate(); // force update async - do not wait for confirmation

      return "SLCTCANV:"s + canv->GetName();
   }

   auto rcanv = GetActiveRCanvas();
   if (rcanv) {
      if (rcanv->NumPrimitives() > 0) {
         rcanv->Wipe();
         rcanv->Modified();
         rcanv->Update(true);
      }

      // FIXME: how to proceed with TObject ownership here
      TObject *clone = tobj->Clone();
      TH1 *h1 = dynamic_cast<TH1 *>(clone);
      if (h1) h1->SetDirectory(nullptr);

      std::shared_ptr<TObject> ptr;
      ptr.reset(clone);
      rcanv->Draw<RObjectDrawable>(ptr, drawingOptions);
      rcanv->Modified();

      rcanv->Update(true);

      return "SLCTCANV:"s + rcanv->GetTitle();
   }


   printf("No active canvas to process dbl click\n");


   return "";
}

/////////////////////////////////////////////////////////////////////////////////
/// Show or update RBrowser in web window
/// If web window already started - just refresh it like "reload" button does
/// If no web window exists or \param always_start_new_browser configured, starts new window

void ROOT::Experimental::RBrowser::Show(const RWebDisplayArgs &args, bool always_start_new_browser)
{
   auto number = fWebWindow->NumConnections();

   if ((number == 0) || always_start_new_browser) {
      fWebWindow->Show(args);
   } else {
      for (int n=0;n<number;++n)
         WebWindowCallback(fWebWindow->GetConnectionId(n),"RELOAD");
   }
}

///////////////////////////////////////////////////////////////////////////////////////////////////////
/// Hide ROOT Browser

void ROOT::Experimental::RBrowser::Hide()
{
   if (!fWebWindow)
      return;

   fWebWindow->CloseConnections();
}

//////////////////////////////////////////////////////////////////////////////////////////////
/// Create new web canvas, invoked when new canvas created on client side

TCanvas *ROOT::Experimental::RBrowser::AddCanvas()
{
   TString canv_name;
   canv_name.Form("webcanv%d", (int)(fCanvases.size()+1));

   auto canv = std::make_unique<TCanvas>(kFALSE);
   canv->SetName(canv_name.Data());
   canv->SetTitle(canv_name.Data());
   canv->ResetBit(TCanvas::kShowEditor);
   canv->ResetBit(TCanvas::kShowToolBar);
   canv->SetCanvas(canv.get());
   canv->SetBatch(kTRUE); // mark canvas as batch
   canv->SetEditable(kTRUE); // ensure fPrimitives are created
   fActiveCanvas = canv->GetName();

   // create implementation
   TWebCanvas *web = new TWebCanvas(canv.get(), "title", 0, 0, 800, 600);

   // assign implementation
   canv->SetCanvasImp(web);

   // initialize web window, but not start new web browser
   web->ShowWebWindow("embed");

   fCanvases.emplace_back(std::move(canv));

   return fCanvases.back().get();
}

//////////////////////////////////////////////////////////////////////////////////////////////
/// Creates RCanvas for the output

std::shared_ptr<ROOT::Experimental::RCanvas> ROOT::Experimental::RBrowser::AddRCanvas()
{
   std::string name = "rcanv"s + std::to_string(fRCanvases.size()+1);

   auto canv = ROOT::Experimental::RCanvas::Create(name);

   canv->Show("embed");

   fActiveCanvas = name;

   fRCanvases.emplace_back(canv);

   return canv;
}

//////////////////////////////////////////////////////////////////////////////////////////////
/// Returns relative URL for canvas - required for client to establish connection

std::string ROOT::Experimental::RBrowser::GetCanvasUrl(TCanvas *canv)
{
   TWebCanvas *web = dynamic_cast<TWebCanvas *>(canv->GetCanvasImp());
   return fWebWindow->GetRelativeAddr(web->GetWebWindow());
}

//////////////////////////////////////////////////////////////////////////////////////////////
/// Returns relative URL for canvas - required for client to establish connection

std::string ROOT::Experimental::RBrowser::GetRCanvasUrl(std::shared_ptr<RCanvas> &canv)
{
   return "../"s + canv->GetWindowAddr() + "/"s;
}

//////////////////////////////////////////////////////////////////////////////////////////////
/// Returns active web canvas (if any)

TCanvas *ROOT::Experimental::RBrowser::GetActiveCanvas() const
{
   auto iter = std::find_if(fCanvases.begin(), fCanvases.end(), [this](const std::unique_ptr<TCanvas> &canv) { return fActiveCanvas == canv->GetName(); });

   if (iter != fCanvases.end())
      return iter->get();

   return nullptr;
}

//////////////////////////////////////////////////////////////////////////////////////////////
/// Returns active RCanvas (if any)

std::shared_ptr<ROOT::Experimental::RCanvas> ROOT::Experimental::RBrowser::GetActiveRCanvas() const
{
   auto iter = std::find_if(fRCanvases.begin(), fRCanvases.end(), [this](const std::shared_ptr<RCanvas> &canv) { return fActiveCanvas == canv->GetTitle(); });

   if (iter != fRCanvases.end())
      return *iter;

   return nullptr;

}


//////////////////////////////////////////////////////////////////////////////////////////////
/// Close and delete specified canvas

void ROOT::Experimental::RBrowser::CloseCanvas(const std::string &name)
{
   auto iter = std::find_if(fCanvases.begin(), fCanvases.end(), [name](std::unique_ptr<TCanvas> &canv) { return name == canv->GetName(); });

   if (iter != fCanvases.end())
      fCanvases.erase(iter);

   if (fActiveCanvas == name)
      fActiveCanvas.clear();
}

//////////////////////////////////////////////////////////////////////////////////////////////
/// Process client connect

void ROOT::Experimental::RBrowser::SendInitMsg(unsigned connid)
{
   std::vector<std::vector<std::string>> reply;

   for (auto &canv : fCanvases) {
      auto url = GetCanvasUrl(canv.get());
      std::string name = canv->GetName();
      std::vector<std::string> arr = {"root6", url, name};
      reply.emplace_back(arr);
   }

   for (auto &canv : fRCanvases) {
      auto url = GetRCanvasUrl(canv);
      std::string name = canv->GetTitle();
      std::vector<std::string> arr = {"root7", url, name};
      reply.emplace_back(arr);
   }

   std::string msg = "INMSG:";
   msg.append(TBufferJSON::ToJSON(&reply, TBufferJSON::kNoSpaces).Data());

   printf("Init msg %s\n", msg.c_str());

   fWebWindow->Send(connid, msg);
}

//////////////////////////////////////////////////////////////////////////////////////////////
/// Return the current directory of ROOT

std::string ROOT::Experimental::RBrowser::GetCurrentWorkingDirectory()
{
   return "GETWORKDIR: { \"path\": \""s + fWorkingDirectory + "\"}"s;
}

//////////////////////////////////////////////////////////////////////////////////////////////
/// receive data from client

void ROOT::Experimental::RBrowser::WebWindowCallback(unsigned connid, const std::string &arg)
{
   size_t len = arg.find("\n");
   if (len != std::string::npos)
      printf("Recv %s\n", arg.substr(0, len).c_str());
   else
      printf("Recv %s\n", arg.c_str());

   if (arg == "QUIT_ROOT") {

      fWebWindow->TerminateROOT();

   } else if (arg.compare(0,6, "BRREQ:") == 0) {
      // central place for processing browser requests
      auto json = ProcessBrowserRequest(arg.substr(6));
      if (json.length() > 0) fWebWindow->Send(connid, json);
   } else if (arg.compare("NEWCANVAS") == 0) {

      std::vector<std::string> reply;

      if (GetUseRCanvas()) {
         auto canv = AddRCanvas();

         auto url = GetRCanvasUrl(canv);

         reply = {"root7"s, url, canv->GetTitle()};

      } else {
         // create canvas
         auto canv = AddCanvas();

         auto url = GetCanvasUrl(canv);

         reply = {"root6"s, url, std::string(canv->GetName())};
      }

      std::string res = "CANVS:";
      res.append(TBufferJSON::ToJSON(&reply, TBufferJSON::kNoSpaces).Data());

      fWebWindow->Send(connid, res);
   } else if (arg.compare(0,7, "DBLCLK:") == 0) {

      if (arg.at(8) != '[') {
         auto str = ProcessDblClick(arg.substr(7), "");
         fWebWindow->Send(connid, str);
      } else {
         auto arr = TBufferJSON::FromJSON<std::vector<std::string>>(arg.substr(7));
         if (arr) {
            auto str = ProcessDblClick(arr->at(0), arr->at(1));
            if (str.length() > 0) {
               fWebWindow->Send(connid, str);
            }
         }
      }
   } else if (arg.compare(0,9, "RUNMACRO:") == 0) {
      ProcessRunCommand(arg.substr(9));
   } else if (arg.compare(0,9, "SAVEFILE:") == 0) {
      ProcessSaveFile(arg.substr(9));
   } else if (arg.compare(0,14, "SELECT_CANVAS:") == 0) {
      fActiveCanvas = arg.substr(14);
      printf("Select %s\n", fActiveCanvas.c_str());
   } else if (arg.compare(0,13, "CLOSE_CANVAS:") == 0) {
      CloseCanvas(arg.substr(13));
   } else if (arg.compare(0, 11, "GETWORKDIR:") == 0) {
      std::string res = GetCurrentWorkingDirectory();
      fWebWindow->Send(connid, res);
   } else if (arg.compare(0, 6, "CHDIR:") == 0) {
      fWorkingDirectory = arg.substr(6);
      fBrowsable.SetTopItem(std::make_unique<RBrowsableSysFileElement>(fWorkingDirectory));
      gSystem->ChangeDirectory(fWorkingDirectory.c_str());
      fWebWindow->Send(connid, GetCurrentWorkingDirectory());
   }
}